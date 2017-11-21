import logging
import time

from . import process, misc

try:
    from shlex import quote as cmd_quote
except ImportError:
    from pipes import quote as cmd_quote

log = logging.getLogger('rclone')


class RcloneUploader:
    def __init__(self, name, config, dry_run=False):
        self.name = name
        self.config = config
        self.dry_run = dry_run

    def delete_file(self, path):
        try:
            log.debug("Deleting file '%s' from remote %s", path, self.name)
            # build cmd
            cmd = "rclone delete %s" % cmd_quote(path)
            if self.dry_run:
                cmd += ' --dry-run'

            # exec
            log.debug("Using: %s", cmd)
            resp = process.execute(cmd, logs=False)
            if 'Failed to delete' in resp:
                return False

            return True
        except Exception:
            log.exception("Exception deleting file '%s' from remote %s: ", path, self.name)
        return False

    def delete_folder(self, path):
        try:
            log.debug("Deleting folder '%s' from remote %s", path, self.name)
            # build cmd
            cmd = "rclone rmdir %s" % cmd_quote(path)
            if self.dry_run:
                cmd += ' --dry-run'

            # exec
            log.debug("Using: %s", cmd)
            resp = process.execute(cmd, logs=False)
            if 'Failed to rmdir' in resp:
                return False

            return True
        except Exception:
            log.exception("Exception deleting folder '%s' from remote %s: ", path, self.name)
        return False

    def upload(self, callback):
        try:
            log.debug("Uploading '%s' to '%s'", self.config['upload_folder'], self.config['upload_remote'])
            # build cmd
            cmd = "rclone move %s %s" % (
                cmd_quote(self.config['upload_folder']), cmd_quote(self.config['upload_remote']))

            extras = self.__extras2string()
            if len(extras) > 2:
                cmd += ' %s' % extras
            excludes = self.__excludes2string()
            if len(excludes) > 2:
                cmd += ' %s' % excludes
            if self.dry_run:
                cmd += ' --dry-run'

            # exec
            log.debug("Using: %s", cmd)
            process.execute(cmd, callback)
            return True
        except Exception:
            log.exception("Exception occurred while uploading '%s' to remote: %s", self.config['upload_folder'],
                          self.name)
        return False

    # internals
    def __extras2string(self):
        return ' '.join(
            "%s=%s" % (key, cmd_quote(value) if isinstance(value, str) else value) for (key, value) in
            self.config['rclone_extras'].items()).replace('=None', '').strip()

    def __excludes2string(self):
        return ' '.join(
            "--exclude=%s" % (cmd_quote(value) if isinstance(value, str) else value) for value in
            self.config['rclone_excludes']).replace('=None', '').strip()


class RcloneSyncer:
    def __init__(self, from_remote, to_remote, **kwargs):
        self.from_config = from_remote
        self.to_config = to_remote

        # trigger logic
        self.rclone_sleeps = misc.merge_dicts(self.from_config['rclone_sleeps'], self.to_config['rclone_sleeps'])
        self.trigger_tracks = {}
        self.delayed_check = 0
        self.delayed_trigger = None

        # pass rclone_extras from kwargs
        if 'rclone_extras' in kwargs:
            self.rclone_extras = kwargs['rclone_extras']
        else:
            self.rclone_extras = {}

        # pass dry_run from kwargs
        if 'dry_run' in kwargs:
            self.dry_run = kwargs['dry_run']
        else:
            self.dry_run = False

    def sync_logic(self, data):
        # loop sleep triggers
        for trigger_text, trigger_config in self.rclone_sleeps.items():
            # check/reset trigger timeout
            if trigger_text in self.trigger_tracks and self.trigger_tracks[trigger_text]['expires'] != '':
                if time.time() >= self.trigger_tracks[trigger_text]['expires']:
                    log.warning("Tracking of trigger: %r has expired, resetting occurrence count and timeout",
                                trigger_text)
                    self.trigger_tracks[trigger_text] = {'count': 0, 'expires': ''}

            # check if trigger_text is in data
            if trigger_text.lower() in data.lower():
                # check / increase tracking count of trigger_text
                if trigger_text not in self.trigger_tracks or self.trigger_tracks[trigger_text]['count'] == 0:
                    # set initial tracking info for trigger
                    self.trigger_tracks[trigger_text] = {'count': 1, 'expires': time.time() + trigger_config['timeout']}
                    log.warning("Tracked first occurrence of trigger: %r. Expiring in %d seconds at %s", trigger_text,
                                trigger_config['timeout'], time.strftime('%Y-%m-%d %H:%M:%S',
                                                                         time.localtime(
                                                                             self.trigger_tracks[trigger_text][
                                                                                 'expires'])))
                else:
                    # trigger_text WAS seen before increase count
                    self.trigger_tracks[trigger_text]['count'] += 1
                    log.warning("Tracked trigger: %r has occurred %d/%d times within %d seconds", trigger_text,
                                self.trigger_tracks[trigger_text]['count'], trigger_config['count'],
                                trigger_config['timeout'])

                    # check if trigger_text was found the required amount of times to abort
                    if self.trigger_tracks[trigger_text]['count'] >= trigger_config['count']:
                        log.warning(
                            "Tracked trigger %r has reached the maximum limit of %d occurrences within %d seconds,"
                            " aborting upload...", trigger_text, trigger_config['count'], trigger_config['timeout'])
                        self.delayed_check = trigger_config['sleep']
                        self.delayed_trigger = trigger_text
                        return True
        return False

    # internals
    def __extras2string(self):
        return ' '.join(
            "%s=%s" % (key, cmd_quote(value) if isinstance(value, str) else value) for (key, value) in
            self.rclone_extras.items()).replace('=None', '').strip()
