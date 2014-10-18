from setuptools import setup

setup(
    name='mirrormug',
    version='0.1',
    py_modules=['mirrormug'],
    install_requires=[
        'click',
        'requests',
        'simplejson',
        'smugpy'
    ],
    entry_points='''
        [console_scripts]
        mirrormug=mirrormug:cli
    ''',
)
