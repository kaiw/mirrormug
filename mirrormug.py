#!/usr/bin/env python
from __future__ import print_function

import hashlib
import os
import sys
import ConfigParser

import click
import requests
import simplejson
import smugpy

APP_NAME = 'MirrorMug'
NICKNAME = None
PASSWORD = None
MIRROR_BASE = None
API_KEY = None

CACHE_PATH = os.path.join(click.get_app_dir(APP_NAME), 'metadata.json')
LOCAL_CACHE_PATH = os.path.join(click.get_app_dir(APP_NAME), 'localmd5.json')

SKIP_VALIDATION = -1
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
                continue
            click.secho(
                'File "%s" is the wrong size; re-downloading' % image_path,
                fg='red')

        if any(k in image for k in VIDEO_KEYS):
            click.echo('File "%s" is a video; skipping' % filename)
            continue

        url = image['OriginalURL']
        md5sum = image.get('MD5Sum')
        missing_images.append((image_path, url, md5sum))
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
        for image_path, url, checked_md5sum in paths:
            req = session.get(url)
            if checked_md5sum:
                md5sum = hashlib.md5()
                md5sum.update(req.content)
                if md5sum.hexdigest() != checked_md5sum:
                    click.secho(
                        'Checksum for downloaded image %s incorrect; skipping '
                        'image' % image_path, fg='red')
                    continue

            if not req.content:
                click.secho(
                    'Downloaded image %s is empty; skipping ' % url, fg='red')
                continue

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


def setup_client():
    global smugmug
    smugmug = smugpy.SmugMug(
        api_key=API_KEY, api_version="1.2.2", app_name=APP_NAME)
    if PASSWORD:
        smugmug.login_withPassword(
            EmailAddress=NICKNAME, Password=PASSWORD)
    else:
        smugmug.login_anonymously()


@click.group()
def cli():
    have_config = read_config()
    if not have_config:
        if not click.confirm('Setup config now?', default=True):
            click.echo('Config missing; can\'t continue')
            raise click.Abort()
        setup()

    setup_client()


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


@cli.command()
def cachealbumsremote():

    try:
        with open(CACHE_PATH) as f:
            old_cache = simplejson.load(f)
    except Exception:
        old_cache = {}

    old_albums = {
        album['id']: album for album in old_cache['albums']['Albums']}

    album_cache = smugmug.albums_get(NickName=NICKNAME, Heavy=True)
    image_cache = {}
    metadata_cache = {
        'albums': album_cache,
        'images': image_cache,
    }
    with click.progressbar(
            album_cache["Albums"], label='Caching albums') as albums:
        for album in albums:
            old_album = old_albums.get(album['id'], {})
            old_updated = old_album.get('LastUpdated', '')
            updated = album['LastUpdated']

            if updated == old_updated:
                images = old_cache['images'][str(album['id'])]
            else:
                images = smugmug.images_get(
                    AlbumID=album['id'], AlbumKey=album['Key'], Heavy=True)
            image_cache[album['id']] = images

    with open(CACHE_PATH, 'w') as f:
        simplejson.dump(metadata_cache, f, indent=2)

    return metadata_cache


def get_local_md5sums():
    import hashlib

    try:
        with open(LOCAL_CACHE_PATH) as f:
            old_cache = simplejson.load(f)['md5']
    except Exception:
        old_cache = {}

    dir_count = 0
    for (base, dirs, files) in os.walk(MIRROR_BASE):
        dir_count += len(dirs)

    filename_encoding = sys.getfilesystemencoding()
    md5_cache = {}

    def progress_item_display(progress_item):
        if not progress_item:
            return ''
        base, dirs, files = progress_item
        return os.path.basename(base)

    with click.progressbar(
            os.walk(MIRROR_BASE),
            label='Scanning folders',
            length=dir_count,
            item_show_func=progress_item_display) as walk:
        for walk_iter in walk:
            base, dirs, files = walk_iter
            for filename in files:
                path = os.path.join(base, filename)
                mtime = os.path.getmtime(path)

                old_mtime, old_md5 = old_cache.get(
                    path.decode(filename_encoding), (None, None))
                if mtime == old_mtime:
                    md5 = old_md5
                else:
                    md5sum = hashlib.md5()
                    with open(path) as f:
                        md5sum.update(f.read())
                    md5 = md5sum.hexdigest()
                # Even though file paths are bytestrings, because what we care
                # about here is a faithful reproduction of the remote albums,
                # storing these as unicode is really what we want.
                unicode_path = path.decode(filename_encoding)
                md5_cache[unicode_path] = [mtime, md5]

    with open(LOCAL_CACHE_PATH, 'w') as f:
        blob = {'md5': md5_cache}
        simplejson.dump(blob, f, indent=2)

    return {k: md5 for k, (mtime, md5) in md5_cache.items()}


def get_remote_data():
    with open(CACHE_PATH) as f:
        return simplejson.load(f)


@cli.command()
def checkalbums():

    cached_data = get_remote_data()
    album_cache = cached_data['albums']['Albums']
    image_cache = cached_data['images']

    remote_md5s = {}

    for album in album_cache:
        mirror_path = get_mirror_path(album)

        images = image_cache[str(album['id'])]
        for image in images['Album']['Images']:
            filename = image['FileName']
            image_path = os.path.join(mirror_path, filename)

            # Skip validating video files
            if any(k in image for k in VIDEO_KEYS):
                remote_md5s[image_path] = SKIP_VALIDATION
                continue

            try:
                remote_md5s[image_path] = image['MD5Sum']
            except KeyError:
                click.secho(
                    'Missing MD5 sum for %s' % image_path, fg='red')

    local_md5s = get_local_md5sums()

    # Purely MD5-based checks

    missing_paths = {k for k in remote_md5s if k not in local_md5s}

    # MD5 + path-based checks

    remote_md5_paths = {v: k for k, v in remote_md5s.items()}
    local_md5_paths = {v: k for k, v in local_md5s.items()}

    incorrect_paths = []
    extra_paths = []
    incorrect_md5s = []

    for md5, path in local_md5_paths.items():
        remote_md5 = remote_md5s.get(path)
        remote_path = remote_md5_paths.get(md5)
        if remote_path:
            if remote_path != path:
                incorrect_paths.append((path, remote_path))
        elif remote_md5:
            if remote_md5 != md5 and remote_md5 != SKIP_VALIDATION:
                incorrect_md5s.append(path)
        else:
            extra_paths.append(path)

    if missing_paths:
        click.secho("Images not mirrored locally:", bold=True)
        for path in sorted(missing_paths):
            click.echo(" * %s" % path)
        click.echo()

    if incorrect_paths:
        click.secho("Images found in the wrong location:", bold=True)
        for path, remote_path in sorted(incorrect_paths):
            click.echo("Image at %s should be at %s" % (path, remote_path))
        click.echo()

    if incorrect_md5s:
        click.secho("Images with bad checksums:", bold=True)
        for path in sorted(incorrect_md5s):
            click.echo(" * %s" % path)
        click.echo()

    if extra_paths:
        click.secho("Images not synced to SmugMug:", bold=True)
        for path in sorted(extra_paths):
            click.echo(" * %s" % path)
        click.echo()

    if any((missing_paths, incorrect_paths, incorrect_md5s, extra_paths)):
        sys.exit(1)


@cli.command()
def findduplicates():
    local_md5s = get_local_md5sums()

    seen_md5s = {}
    duplicate_paths = []
    for path, md5 in local_md5s.items():
        if md5 in seen_md5s:
            duplicate_paths.append((seen_md5s[md5], path))
        else:
            seen_md5s[md5] = path

    if duplicate_paths:
        click.secho("Duplicate images:", bold=True)
        for path1, path2 in sorted(duplicate_paths):
            click.echo(" * %s is also at %s" % (path1, path2))
    else:
        click.secho("No duplicates found", bold=True)
    click.echo()


if __name__ == '__main__':
    cli()
