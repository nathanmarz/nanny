from setuptools import setup

setup(
    name='nanny',
    version='0.1.0', #Correct version?
    install_requires=['paramiko'],
    entry_points={
        'console_scripts' : ['nanny=nanny:main'],
    },
    py_modules = ['nanny'],
)
