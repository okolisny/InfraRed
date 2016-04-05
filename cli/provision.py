#!/usr/bin/env python
import os
import logging

import yaml

from cli import logger  # logger creation is first thing to be done
from cli import conf
from cli import utils
from cli import exceptions
from cli import spec
import cli.yamls
import cli.execute

LOG = logger.LOG
CONF = conf.config_wrapper

APPLICATION = 'provisioner'
PROVISION_PLAYBOOK = "provision.yaml"
CLEANUP_PLAYBOOK = "cleanup.yaml"
NON_SETTINGS_OPTIONS = ['command0', 'verbose', 'extra-vars', 'output',
                        'input', 'dry-run', 'cleanup', 'inventory']


def get_arguments_dict(spec_args):
    """
    Collect all ValueArgument args in dict according to arg names

    some-key=value will be nested in dict as:

    {"some": {
        "key": value}
    }

    For `YamlFileArgument` value is path to yaml so file content
    will be loaded as a nested dict.

    :param spec_args: Dictionary based on cmd-line args parsed from spec file
    :return: dict
    """
    settings_dict = {}
    for _name, argument in spec_args.iteritems():
        if isinstance(argument, spec.ValueArgument):
            utils.dict_insert(settings_dict, argument.value,
                              *argument.arg_name.split("-"))
    return settings_dict


class IRFactory(object):
    """
    Creates and configures the IR applications.
    """

    @classmethod
    def create(cls, app_name, config, args=None):
        """
        Create the application object
        by module name and provided configuration.

        :param app_name: str
        :param config: dict. configuration details
        :param args: list. If given parse it instead of stdin input.
        """
        settings_dirs = config.get_settings_dirs()

        if app_name in ["provisioner", ]:
            app_settings_dirs = config.build_app_settings_dirs(app_name)
            spec_args = spec.parse_args(app_settings_dirs, args)
            cls.configure_environment(spec_args)

            if spec_args.get('generate-conf-file', None):
                LOG.debug('Conf file "{}" has been generated. Exiting'.format(
                    spec_args['generate-conf-file']))
                app_instance = None
            else:
                app_instance = IRApplication(
                    app_name, settings_dirs, spec_args)

        else:
            raise exceptions.IRUnknownApplicationException(
                "Application is not supported: '{}'".format(app_name))
        return app_instance

    @classmethod
    def configure_environment(cls, args):
        """
        Performs the environment configuration.
        :param args:
        :return:
        """
        if args['debug']:
            LOG.setLevel(logging.DEBUG)
            # todo(yfried): load exception hook now and not at init.


class IRSubCommand(object):
    """
    Represents a command (virsh, ospd, etc)
    for the application
    """

    def __init__(self, name, args, settings_dirs):
        self.name = name
        self.args = args
        self.settings_dirs = settings_dirs

    @classmethod
    def create(cls, app, settings_dirs, args):
        """
        Constructs the sub-command.
        :param app:  tha application name
        :param settings_dirs:  the default application settings dirs
        :param args: the application args
        :return: the IRSubCommand instance.
        """
        if args:
            settings_dirs = [os.path.join(settings_dir,
                                          app) for settings_dir in
                             settings_dirs]
        if "command0" in args:
            settings_dirs = [os.path.join(settings_dir,
                                          args['command0']) for settings_dir in
                             settings_dirs]
        return cls(args['command0'], args, settings_dirs)

    def get_settings_files(self):
        """
        Collects all the settings files for given application and sub-command
        """
        settings_files = []

        # first take all input files from args
        for input_file in self.args['input'] or []:
            settings_files.append(utils.normalize_file(input_file))

        # get the sub-command yml file
        for settings_dir in self.settings_dirs:
            path = os.path.join(
                settings_dir,
                self.name + '.yml')
            if os.path.exists(path):
                settings_files.append(path)

        LOG.debug("All settings files to be loaded:\n%s" % settings_files)
        return settings_files


class IRApplication(object):
    """
    Hold the default application workflow logic.
    """

    def __init__(self, name, settings_dirs, args):
        self.name = name
        self.args = args
        self.settings_dirs = settings_dirs
        self.sub_command = IRSubCommand.create(name, settings_dirs, args)

    def run(self):
        """
        Runs the application
        """
        settings = self.collect_settings()
        self.dump_settings(settings)

        if not self.args['dry-run']:
            self.args['settings'] = yaml.load(yaml.safe_dump(
                settings,
                default_flow_style=False))

            if self.args['cleanup']:
                cli.execute.ansible_playbook(CLEANUP_PLAYBOOK,
                                             verbose=self.args["verbose"],
                                             settings=self.args["settings"])
            else:
                cli.execute.ansible_playbook(PROVISION_PLAYBOOK,
                                             verbose=self.args["verbose"],
                                             settings=self.args["settings"])

    def collect_settings(self):
        settings_files = self.sub_command.get_settings_files()
        arguments_dict = {APPLICATION: get_arguments_dict(self.args)}

        # todo(yfried): fix after lookup refactor
        # utils.dict_merge(settings_files, arguments_dict)
        # return self.lookup(settings_files)

        # todo(yfried) remove this line after lookup refactor
        return self.lookup(settings_files, arguments_dict)

    def lookup(self, settings_files, settings_dict):
        """
        Replaces a setting values with !lookup
        in the setting files by values from
        other settings files.
        """

        cli.yamls.Lookup.settings = utils.generate_settings(settings_files)
        # todo(yfried) remove this line after refactor
        cli.yamls.Lookup.settings.merge(settings_dict)
        cli.yamls.Lookup.settings = utils.merge_extra_vars(
            cli.yamls.Lookup.settings,
            self.args['extra-vars'])

        cli.yamls.Lookup.in_string_lookup()

        return cli.yamls.Lookup.settings

    def dump_settings(self, settings):
        LOG.debug("Dumping settings...")
        output = yaml.safe_dump(settings,
                                default_flow_style=False)
        dump_file = self.args['output']
        if dump_file:
            LOG.debug("Dump file: {}".format(dump_file))
            with open(dump_file, 'w') as output_file:
                output_file.write(output)
        else:
            print output


def main():
    app = IRFactory.create(APPLICATION, CONF)
    if app:
        app.run()


if __name__ == '__main__':
    main()
