import cmd
import atexit
import textwrap
from time import sleep

from threading import Thread

import sqlalchemy as _alchy
from sqlalchemy.orm import relationship

import zmq
from vexmessage import decode_vex_message

from vexbot import __version__
from vexbot.argenvconfig import ArgEnvConfig
from vexbot.adapters.messaging import ZmqMessaging
from vexbot.command_managers import CommandManager
from vexbot.settings_manager import SettingsManager

from vexbot.commands.start_vexbot import start_vexbot as _start_vexbot
from vexbot.sql_helper import Base
# from vexbot.commands.call_editor import call_editor


class ShellSettings(Base):
    __tablename__ = 'shell_settings'
    id = _alchy.Column(_alchy.Integer, primary_key=True)
    history_filepath = _alchy.Column(_alchy.String(length=4096))
    robot_settings = relationship("RobotSettings")
    robot_settings_id = _alchy.Column(_alchy.Integer,
                                      _alchy.ForeignKey('robot_settings.id'))


class Shell(cmd.Cmd):
    def __init__(self,
                 context='default',
                 prompt_name='vexbot',
                 publish_address=None,
                 subscribe_address=None,
                 **kwargs):

        super().__init__()
        self.settings_manager = SettingsManager(context=context)
        self.messaging = ZmqMessaging('shell',
                                      publish_address,
                                      subscribe_address,
                                      'shell')

        self.command_manager = CommandManager(self.messaging)

        # NOTE: Hack. Command manager comes with defatul `command` command. 
        # this ensures that the command goes to the robot, which returns a
        # a list of all commands
        self.command_manager._commands.pop('commands')
        self.stdout.write('Vexbot {}\n'.format(__version__))
        if kwargs.get('already_running', False):
            self.stdout.write('vexbot already running\n')
        self.stdout.write("    Type \"help\" for command line help or "
                          "\"commands\" for bot commands\n    NOTE: "
                          "\"commands\" will only work if bot is running\n\n")

        self.messaging.start_messaging()
        self._context = context
        self.do_context(context)

        self.prompt = prompt_name + ': '
        self.misc_header = "Commands"
        self._exit_loop = False
        self._set_readline_helper(kwargs.get('history_file'))

    def default(self, arg):
        if not self.command_manager.is_command(arg, call_command=True):
            command, argument, line = self.parseline(arg)

            self.messaging.send_command(command=command,
                                        args=argument,
                                        line=line)

            if self._context is None:
                self.stdout.write('\nNo context set! Use `contexts` to see '
                                  'stored robot contexts and the `context` '
                                  'command to set the shell context\n\n')

    def _set_readline_helper(self, history_file=None):
        try:
            import readline
        except ImportError:
            return

        try:
            readline.read_history_file(history_file)
        except IOError:
            pass
        readline.set_history_length(1000)
        atexit.register(readline.write_history_file, history_file)

    def run(self):
        frame = None
        while True and not self._exit_loop:
            try:
                # NOTE: not blocking here to check the _exit_loop condition
                frame = self.messaging.sub_socket.recv_multipart(zmq.NOBLOCK)
            except zmq.error.ZMQError:
                pass

            sleep(.5)

            if frame:
                message = decode_vex_message(frame)
                # NOTE: No message type other than `RSP` currently handeled
                if message.type == 'RSP':
                    self.stdout.write("\n{}\n".format(self.doc_leader))
                    header = message.contents.get('original', 'Response')
                    contents = message.contents.get('response', None)
                    # FIXME
                    if (isinstance(header, (tuple, list))
                            and isinstance(contents, (tuple, list))
                            and contents):

                        for head, content in zip(header, contents):
                            self.print_topics(head, (contents,), 15, 70)
                    else:
                        if isinstance(contents, str):
                            contents = (contents,)
                        self.print_topics(header,
                                          contents,
                                          15,
                                          70)

                    self.stdout.write("vexbot: ")
                    self.stdout.flush()
                frame = None

    def _create_command_function(self, command):
        def resulting_function(arg):
            self.default(' '.join((command, arg)))
        return resulting_function

    def _prompt_helper(self, prompt, default=None):
        """
        used in `do_create_robot_settings`
        """
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if not len(line):
            line = 'EOF'
        else:
            line = line.rstrip('\r\n')

        if not line in ('EOF', 'STOP'):
            if line == '' and not default is None:
                line = default

            # TODO: Clean up
            self.stdout.write('    ' + line + '\n\n')

            return line

        return None

    def _get_old_settings(self, setting_manager, context):
        """
        returns settings minus the `_sa_instance_state`
        used in `do_create_robot_settings`
        """
        old_settings = self.settings_manager.get_robot_settings(context)
        if old_settings is None:
            return dict()
        old_settings = dict(old_settings.__dict__)
        old_settings.pop('_sa_instance_state')
        return old_settings

    def do_start_bot(self, arg):
        if arg == '':
            arg = self._context
        _start_vexbot(arg)

    def do_update_robot_settings(self, arg):
        if arg == '':
            self.do_contexts('')

        self.do_create_robot_settings(arg)


    def do_create_robot_settings(self, arg):
        self.stdout.write('\n' + textwrap.fill('Default values are shown in `'
                                               '[]` after the prompt name. Pre'
                                               'ssing enter accpets the defaul'
                                               't value',
                                               initial_indent='    ',
                                               subsequent_indent='        ')
                                               + '\n\n')

        s = {}
        settings_manager = SettingsManager()
        if arg == '':
            arg = 'default'

        s['context'] = self._prompt_helper('context [{}]: '.format(arg), arg)
        if s['context'] is None:
            self.stdout.write('\n')
            return

        s.update(self._get_old_settings(settings_manager, s['context']))
        s['name'] = self._prompt_helper('name [{}]: '.format(s.get('name', 'vexbot')),
                                        s.get('name', 'vexbot'))

        if s['name'] is None:
            self.stdout.write('\n')
            return

        s['subscribe_address'] = self._prompt_helper('subscribe_address [{}]: '.format(s.get('subscribe_address',
                                                                                       'tcp://127.0.0.1:4000')),
                                               s.get('subscribe_address',
                                                     'tcp://127.0.0.1:4000'))

        if s['subscribe_address'] is None:
            self.stdout.write('\n')
            return

        s['publish_address'] = self._prompt_helper('publish address [{}]: '.format(s.get('publish_address', 'tcp://127.0.0.1:4001')),
                                               s.get('publish_address', 'tcp://127.0.0.1:4001'))

        if s['publish_address'] is None:
            self.stdout.write('\n')
            return

        s['monitor_address'] = self._prompt_helper('monitor address [{}]: '.format(s.get('monitor_address', '')),
                                               s.get('monitor_address', ''))

        if s['monitor_address'] is None:
            self.stdout.write('\n')
            return

        # FIXME
        starting_adapters = ' '.join(s.get('starting_adapters', ()))

        starting_adapters = self._prompt_helper('starting adapters [{}]: '.format(starting_adapters),
                                                starting_adapters)

        if starting_adapters is not None:
            starting_adapters = starting_adapters.lower().split()
        else:
            starting_adapters = []

        s['starting_adapters'] = starting_adapters

        if 'id' in s:
            settings_manager.update_robot_settings(s)
        else:
            settings_manager.create_robot_settings(s)

        if s['context'] == self._context:
            self.do_context(self._context)

    def do_EOF(self, arg):
        self.stdout.write('\n')
        # NOTE: This ensures we exit out of the `run` method on EOF
        self._exit_loop = True
        return True

    def get_names(self):
        names = dir(self)
        # NOTE: Adds the names from the command manager to the autocomplete helper
        names.extend(['do_' + a for a in self.command_manager._commands.keys()])
        return names

    def do_context(self, arg):
        if arg:
            return self.do_contexts(arg)
        context = self._context
        if context is None:
            context = 'NONE SET'
        self.stdout.write('\n' + context + '\n\n')

    def do_contexts(self, arg):
        if arg:
            # Do this first for now, in case our user messes up
            settings = self.settings_manager.get_robot_settings(arg)
            if settings is None:
                return
            # FIXME----
            if self.messaging._pub_address:
                self.messaging.pub_socket.disconnect(self.messaging._pub_address)
            if self.messaging._sub_address:
                self.messaging.sub_socket.disconnect(self.messaging._sub_address)
            #------

            self.messaging._pub_address = settings.publish_address
            self.messaging._sub_address = settings.subscribe_address
            self.messaging.update_messaging()
            self._context = arg
        else:
            contexts = self.settings_manager.get_robot_contexts()
            self.stdout.write('\n')
            self.print_topics('contexts',
                              contexts,
                              15,
                              80)

    def do_help(self, arg):
        if arg:
            if self.command_manager.is_command(arg):
                doc = self.command_manager._commands[arg].__doc__
                if doc:
                    self.stdout.write("{}\n".format(str(doc)))
            else:
                self.messaging.send_command(command='help', args=arg)

        else:
            self.stdout.write("{}\n".format(self.doc_leader))
            # TODO: add commands from shell
            commands = set(self.command_manager._commands.keys())
            commands.update(x[3:] for x in self.get_names() if x.startswith('do_'))
            commands.add('commands')
            commands = '\n'.join(commands)

            self.print_topics(self.misc_header,
                              [commands],
                              15,
                              80)

    def add_completion(self, command):
        setattr(self,
                'do_{}'.format(command),
                self._create_command_function(command))

    """
    def _call_editor(self):
        vexdir = create_vexdir()
        code_output = call_editor(vexdir)
        try:
            code = compile(code_output, '<string>', 'exec')
        except Exception as e:
            print(e)

        local = {}
        exec(code, globals(), local)
        # need to add to commands?
        for k, v in local.items():
            if inspect.isfunction(v):
                self.command_manager.register_command(k, v)
    """


def main(**kwargs):
    if not kwargs:
        kwargs = {}
    shell = Shell(**kwargs)
    cmd_loop_thread = Thread(target=shell.run)
    cmd_loop_thread.daemon = True
    cmd_loop_thread.start()

    shell.cmdloop()


if __name__ == '__main__':
    main()
