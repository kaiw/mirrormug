#!/usr/bin/env python
from __future__ import print_function

import os
import ConfigParser

import click
import requests
import smugpy

APP_NAME = 'MirrorMug'
NICKNAME = None
PASSWORD = None
MIRROR_BASE = None
API_KEY = None

VIDEO_KEYS = ('Video320URL', 'Video640URL', 'Video960URL', 'Video1280URL',
              'Video1920URL', 'VideoSMILURL', 'VideoStreamingURL')

smugmug = None


def read_config():
    global NICKNAME, PASSWORD, API_KEY, MIRROR_BASE

    def sane_get(parser, key):
        try:
            return parser.get(section, key)
        except ConfigParser.NoSectionError:
            click.echo('Config section "%s" missing' % section)
        except ConfigParser.NoOptionError:
            click.echo('Config section "%s" missing key "%s"' % (section, key))

    section = 'main'
    config = os.path.join(click.get_app_dir(APP_NAME), 'config.ini')
    try:
        with open(config) as f:
            parser = ConfigParser.RawConfigParser()
            parser.readfp(f)
            NICKNAME = sane_get(parser, 'nickname')
            PASSWORD = sane_get(parser, 'password')
            MIRROR_BASE = sane_get(parser, 'mirrorpath')
            API_KEY = sane_get(parser, 'apikey')
    except IOError:
        pass

    # It's okay to be missing a password
    return NICKNAME and MIRROR_BASE and API_KEY


def write_config():
    app_dir = click.get_app_dir(APP_NAME)
    if not os.path.exists(app_dir):
        os.makedirs(app_dir)

    parser = ConfigParser.RawConfigParser()
    section = 'main'
    parser.add_section(section)
    parser.set(section, 'nickname', NICKNAME)
    parser.set(section, 'password', PASSWORD)
    parser.set(section, 'mirrorpath', MIRROR_BASE)
    parser.set(section, 'apikey', API_KEY)

    config = os.path.join(click.get_app_dir(APP_NAME), 'config.ini')
    try:
        with open(config, 'w') as f:
            parser.write(f)
    except IOError as err:
        click.secho(
            'Couldn\'t write config file: %s' % err, fg='red')


def setup():
    global NICKNAME, PASSWORD, API_KEY, MIRROR_BASE
    NICKNAME = click.prompt('Enter your SmugMug name', default=NICKNAME)
    if not PASSWORD:
        click.secho(
            'If you choose to enter your password here, it will be stored '
            'in plain text in your config.\nDo not enter your password here '
            'if this makes you nervous!', fg='red')
        PASSWORD = click.prompt(
            'Enter your SmugMug password (or leave blank to keep unchanged)',
            default=PASSWORD, hide_input=True, show_default=False)
    # TODO: Would be nice to have a sane, OS-specific default here
    base = click.prompt(
        'Where should your SmugMug galleries be mirrored?',
        default=MIRROR_BASE or os.path.expanduser("~/Pictures"))
    MIRROR_BASE = os.path.expanduser(base)
    API_KEY = click.prompt('Enter your SmugMug API key', default=API_KEY)
    if MIRROR_BASE and API_KEY:
        write_config()


def get_mirror_path(album):
    if not MIRROR_BASE:
        click.echo('Base folder missing from config')
        raise click.Abort()

    if not os.path.exists(MIRROR_BASE):
        click.echo('Base folder missing from disk')
        raise click.Abort()

    path_components = []
    category = album.get('Category', {}).get('Name')
    subcategory = album.get('SubCategory', {}).get('Name')
    title = album['Title']
    if category:
        path_components.append(category)
    if subcategory:
        path_components.append(subcategory)
    path_components.append(title)

    return os.path.abspath(os.path.join(MIRROR_BASE, *path_components))


def get_missing_images(smugmug, album, mirror_path):
    images = smugmug.images_get(
        AlbumID=album['id'], AlbumKey=album['Key'], Heavy=True)
    missing_images = []
    for image in images['Album']['Images']:
        filename = image['FileName']
        image_path = os.path.join(mirror_path, filename)
        if os.path.exists(image_path):
            size = os.stat(image_path).st_size
            if size == image['Size']:
                # TODO: Check MD5; requires authed access
                continue
            click.secho(
                'File "%s" is the wrong size; re-downloading' % image_path,
                fg='red')

        if any(k in image for k in VIDEO_KEYS):
            click.echo('File "%s" is a video; skipping' % filename)
            continue

        url = image['OriginalURL']
        missing_images.append((image_path, url))
    return missing_images


def download_images(image_paths):
    headers = {"User-Agent": smugmug.application}
    cookies = {}
    session_id = getattr(smugmug, 'session_id', None)
    # TODO: This apparently allows downloading of private images, but doesn't
    # actually work in testing.
    if session_id:
        cookies["SMSESS"] = session_id
    session = requests.Session()
    session.headers = headers
    session.cookies = requests.utils.cookiejar_from_dict(cookies)

    with click.progressbar(image_paths, label='Downloading images') as paths:
        for image_path, url in paths:
            req = session.get(url)
            with open(image_path, 'wb') as f:
                f.write(req.content)


def mirror_album(album):
    title = album['Title']
    click.secho(
        '\nChecking album "%s"' % title, bold=True)

    mirror_path = get_mirror_path(album)
    missing_images = get_missing_images(smugmug, album, mirror_path)
    if not missing_images:
        click.secho('Already synced', fg='green')
        return
    click.secho('Found %d missing images for album "%s"' % (
                len(missing_images), title))

    if not click.confirm('Download this album now?', default=True):
        return

    click.echo()
    if not os.path.exists(mirror_path):
        click.echo(
            'Creating missing folder "%s"' % mirror_path)
        os.makedirs(mirror_path)

    download_images(missing_images)


def mirror_albums(album_name=None):
    albums = smugmug.albums_get(NickName=NICKNAME)
    for album in albums["Albums"]:
        if album_name and album['Title'] != album_name:
            continue
        mirror_album(album)


@click.group()
def cli():
    global smugmug

    have_config = read_config()
    if not have_config:
        if not click.confirm('Setup config now?', default=True):
            click.echo('Config missing; can\'t continue')
            raise click.Abort()
        setup()

    smugmug = smugpy.SmugMug(
        api_key=API_KEY, api_version="1.2.2", app_name=APP_NAME)
    if PASSWORD:
        smugmug.login_withPassword(
            EmailAddress=NICKNAME, Password=PASSWORD)
    else:
        smugmug.login_anonymously()


@cli.command()
def listalbums():
    albums = smugmug.albums_get(NickName=NICKNAME)
    for album in albums["Albums"]:
        click.echo(album['Title'])


@cli.command()
@click.argument('album_name')
def getalbum(album_name):
    mirror_albums(album_name)


@cli.command()
def getalbums():
    mirror_albums()


if __name__ == '__main__':
    cli()
