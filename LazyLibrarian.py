#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import os
import sys
import time
import cherrypy
import threading
import locale
import ConfigParser
import platform
import stat

import lazylibrarian
from lazylibrarian import webStart, logger, versioncheck

# The following should probably be made configurable at the settings level
# This fix is put in place for systems with broken SSL (like QNAP)
opt_out_of_certificate_verification = True
if opt_out_of_certificate_verification:
    try:
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context
    except:
        pass
# ==== end block (should be configurable at settings level)


def main():
    # DIFFEREMT
    # rename this thread
    threading.currentThread().name = "MAIN"
    # Set paths
    if hasattr(sys, 'frozen'):
        lazylibrarian.FULL_PATH = os.path.abspath(sys.executable)
    else:
        lazylibrarian.FULL_PATH = os.path.abspath(__file__)

    lazylibrarian.PROG_DIR = os.path.dirname(lazylibrarian.FULL_PATH)
    lazylibrarian.ARGS = sys.argv[1:]

    lazylibrarian.SYS_ENCODING = None

    try:
        locale.setlocale(locale.LC_ALL, "")
        lazylibrarian.SYS_ENCODING = locale.getpreferredencoding()
    except (locale.Error, IOError):
        pass

    # for OSes that are poorly configured I'll just force UTF-8
    # windows cp1252 can't handle some accented author names,
    # eg "Marie Kondō" U+014D: LATIN SMALL LETTER O WITH MACRON, but utf-8 does
    if not lazylibrarian.SYS_ENCODING or lazylibrarian.SYS_ENCODING in ('ANSI_X3.4-1968', 'US-ASCII', 'ASCII') or '1252' in lazylibrarian.SYS_ENCODING:
        lazylibrarian.SYS_ENCODING = 'UTF-8'

    # Set arguments
    from optparse import OptionParser

    p = OptionParser()
    p.add_option('-d', '--daemon', action="store_true",
                 dest='daemon', help="Run the server as a daemon")
    p.add_option('-q', '--quiet', action="store_true",
                 dest='quiet', help="Don't log to console")
    p.add_option('--debug', action="store_true",
                 dest='debug', help="Show debuglog messages")
    p.add_option('--nolaunch', action="store_true",
                 dest='nolaunch', help="Don't start browser")
    p.add_option('--update', action="store_true",
                 dest='update', help="Update to latest version (only git or source installs)")
    p.add_option('--port',
                 dest='port', default=None,
                 help="Force webinterface to listen on this port")
    p.add_option('--datadir',
                 dest='datadir', default=None,
                 help="Path to the data directory")
    p.add_option('--config',
                 dest='config', default=None,
                 help="Path to config.ini file")
    p.add_option('-p', '--pidfile',
                 dest='pidfile', default=None,
                 help="Store the process id in the given file")

    options, args = p.parse_args()

    lazylibrarian.LOGLEVEL = 1
    if options.debug:
        lazylibrarian.LOGLEVEL = 2

    if options.quiet:
        lazylibrarian.LOGLEVEL = 0

    if options.daemon:
        if not 'windows' in platform.system().lower():
            lazylibrarian.DAEMON = True
            #lazylibrarian.LOGLEVEL = 0
            lazylibrarian.daemonize()
        else:
            print "Daemonize not supported under Windows, starting normally"

    if options.nolaunch:
        lazylibrarian.LAUNCH_BROWSER = False

    if options.update:
        lazylibrarian.SIGNAL = 'update'

    if options.datadir:
        lazylibrarian.DATADIR = str(options.datadir)
    else:
        lazylibrarian.DATADIR = lazylibrarian.PROG_DIR

    if options.config:
        lazylibrarian.CONFIGFILE = str(options.config)
    else:
        lazylibrarian.CONFIGFILE = os.path.join(lazylibrarian.DATADIR, "config.ini")

    if options.pidfile:
        if lazylibrarian.DAEMON:
            lazylibrarian.PIDFILE = str(options.pidfile)

    # create and check (optional) paths
    if not os.path.exists(lazylibrarian.DATADIR):
        try:
            os.makedirs(lazylibrarian.DATADIR)
        except OSError:
            raise SystemExit('Could not create data directory: ' + lazylibrarian.DATADIR + '. Exit ...')

    if not os.access(lazylibrarian.DATADIR, os.W_OK):
        raise SystemExit('Cannot write to the data directory: ' + lazylibrarian.DATADIR + '. Exit ...')

    # create database and config
    lazylibrarian.DBFILE = os.path.join(lazylibrarian.DATADIR, 'lazylibrarian.db')
    lazylibrarian.CFG = ConfigParser.RawConfigParser()
    lazylibrarian.CFG.read(lazylibrarian.CONFIGFILE)

    # REMINDER ############ NO LOGGING BEFORE HERE ###############
    # There is no point putting in any logging above this line, as its not set till after initialize.
    lazylibrarian.initialize()

    # Set the install type (win,git,source) &
    # check the version when the application starts
    logger.debug('(LazyLibrarian) Setup install,versions and commit status')
    versioncheck.getInstallType()
    version_file = os.path.join(lazylibrarian.PROG_DIR, 'version.txt')
    # if version file is less than "old" hours old, don't check github at startup
    old = 6
    if os.path.isfile(version_file):
        age = time.time() - os.stat(version_file)[stat.ST_MTIME]
        old = int(age / (60 * 60 * old))
        if not old: # don't call git, read the version file
            fp = open(version_file, 'r')
            lazylibrarian.CURRENT_VERSION = fp.read().strip(' \n\r')
            fp.close()
            lazylibrarian.LATEST_VERSION = "not checked"
            lazylibrarian.COMMITS_BEHIND = 0
            lazylibrarian.COMMIT_LIST = ""
    if old:
        lazylibrarian.CURRENT_VERSION = versioncheck.getCurrentVersion()
        lazylibrarian.LATEST_VERSION = versioncheck.getLatestVersion()
        lazylibrarian.COMMITS_BEHIND, lazylibrarian.COMMIT_LIST = versioncheck.getCommitDifferenceFromGit()

    logger.debug('Current Version [%s] - Latest remote version [%s] - Install type [%s]' % (
        lazylibrarian.CURRENT_VERSION, lazylibrarian.LATEST_VERSION, lazylibrarian.INSTALL_TYPE))

    if lazylibrarian.COMMITS_BEHIND <= 0 and lazylibrarian.SIGNAL == 'update':
        lazylibrarian.SIGNAL = None
        if lazylibrarian.COMMITS_BEHIND == 0:
            logger.debug('Not updating, LazyLibrarian is already up to date')
        else:
            logger.debug('Not updating, LazyLibrarian has local changes')

    if lazylibrarian.SIGNAL == 'update':
        if lazylibrarian.INSTALL_TYPE not in  ['git', 'source']:
            lazylibrarian.SIGNAL = None
            logger.debug('Not updating, not a git or source installation')

    if options.port:
        lazylibrarian.HTTP_PORT = int(options.port)
        logger.info('Starting LazyLibrarian on forced port: %s, webroot "%s"' %
                    (lazylibrarian.HTTP_PORT, lazylibrarian.HTTP_ROOT))
    else:
        lazylibrarian.HTTP_PORT = int(lazylibrarian.HTTP_PORT)
        logger.info('Starting LazyLibrarian on port: %s, webroot "%s"' %
                    (lazylibrarian.HTTP_PORT, lazylibrarian.HTTP_ROOT))

    if lazylibrarian.DAEMON:
        lazylibrarian.daemonize()

    # Try to start the server.
    webStart.initialize({
        'http_port': lazylibrarian.HTTP_PORT,
        'http_host': lazylibrarian.HTTP_HOST,
        'http_root': lazylibrarian.HTTP_ROOT,
        'http_user': lazylibrarian.HTTP_USER,
        'http_pass': lazylibrarian.HTTP_PASS,
        'http_proxy': lazylibrarian.HTTP_PROXY,
        'https_enabled': lazylibrarian.HTTPS_ENABLED,
        'https_cert': lazylibrarian.HTTPS_CERT,
        'https_key': lazylibrarian.HTTPS_KEY,
    })

    if lazylibrarian.LAUNCH_BROWSER and not options.nolaunch:
        lazylibrarian.launch_browser(lazylibrarian.HTTP_HOST, lazylibrarian.HTTP_PORT, lazylibrarian.HTTP_ROOT)

    lazylibrarian.start()

    while True:
        if not lazylibrarian.SIGNAL:

            try:
                time.sleep(1)
            except KeyboardInterrupt:
                lazylibrarian.shutdown()
        else:
            if lazylibrarian.SIGNAL == 'shutdown':
                lazylibrarian.shutdown()
            elif lazylibrarian.SIGNAL == 'restart':
                lazylibrarian.shutdown(restart=True)
            else:
                lazylibrarian.shutdown(restart=True, update=True)
            lazylibrarian.SIGNAL = None
    return

if __name__ == "__main__":
    main()
