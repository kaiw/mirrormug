mirrormug
=========

A simple command-line tool for mirroring your SmugMug albums locally.

* Install with `python setup.py install`
* Run with `mirrormug <command>`
* On first run, you'll be prompted to set up account details.
* In order to use this, you *must have a SmugMug API key*. Don't worry, they're easy to get! Just go to http://www.smugmug.com/hack/apikeys and enter some details.

Currently supported commands are:

* `listalbums` - Show all albums associated with an account
* `getalbum "<album>"` - Mirror a single album. Albums are named, and need to be entered exactly as listed.
* `getalbums` - Mirror all albums, prompting for each one.


Limitations
-----------

Videos and private images are currently not supported, but both are on the to-do list.
