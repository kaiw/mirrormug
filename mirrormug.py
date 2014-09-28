#!/usr/bin/env python
from __future__ import print_function

import os
import ConfigParser

import click
import requests
import smugpy

NICKNAME = None
APP_NAME = 'MirrorMug'
MIRROR_BASE = None
API_KEY = None

smugmug = None


def read_config():
    global API_KEY, MIRROR_BASE

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
            MIRROR_BASE = sane_get(parser, 'mirrorpath')
            API_KEY = sane_get(parser, 'apikey')
    except IOError:
        pass

    return MIRROR_BASE and API_KEY


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

        url = image['OriginalURL']
        missing_images.append((image_path, url))
    return missing_images


def download_images(image_paths):
    with click.progressbar(image_paths, label='Downloading images') as paths:
        for image_path, url in paths:
            req = requests.get(url)
            with open(image_path, 'wb') as f:
                f.write(req.content)


@click.group()
@click.pass_context
def cli(ctx):
    global smugmug

    have_config = read_config()
    if not have_config:
        if not click.confirm('Setup config now?', default=True):
            click.echo('Config missing; can\'t continue')
            raise click.Abort()
        ctx.forward(setup)

    smugmug = smugpy.SmugMug(
        api_key=API_KEY, api_version="1.3.0", app_name="mugmirror")


@cli.command()
def setup():
    click.echo('Setup not implemented')
    raise click.Abort()


@cli.command()
def syncall():
    albums = smugmug.albums_get(NickName=NICKNAME)

    for album in albums["Albums"]:
        title = album['Title']
        click.secho(
            '\nChecking album "%s"' % title, bold=True)

        mirror_path = get_mirror_path(album)
        missing_images = get_missing_images(smugmug, album, mirror_path)
        if not missing_images:
            click.secho('Already synced', fg='green')
            continue
        click.secho('Found %d missing images for album "%s"' % (
                    len(missing_images), title))

        if not click.confirm('Download this album now?', default=True):
            continue

        click.echo()
        if not os.path.exists(mirror_path):
            click.echo(
                'Creating missing folder "%s"' % mirror_path)
            os.makedirs(mirror_path)

        download_images(missing_images)


if __name__ == '__main__':
    cli()
