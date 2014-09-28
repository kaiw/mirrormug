from setuptools import setup

setup(
    name='mirrormug',
    version='0.1',
    py_modules=['mirrormug'],
    install_requires=[
        'click',
        'requests',
        'smugpy'
    ],
    entry_points='''
        [console_scripts]
        mirrormug=mirrormug:cli
    ''',
)
