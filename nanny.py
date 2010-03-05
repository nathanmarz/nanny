'''
Copyright 2010 Nathan Marz

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

from __future__ import with_statement
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from paramiko import SSHClient

from optparse import OptionParser
from _config.nannyconstants import *
import sys
import os
import shutil

'''
TODO: should lock the repository
 - should we just use svn or git as the repository?
'''

def get_substance(strs):
    return filter(lambda x: len(x) > 0, map(lambda x: x.strip(), strs)) 

def get_substance_lines(file_path):
    f = open(file_path, "r")
    lines = f.readlines()
    f.close()
    return get_substance(lines)

def parse_version(raw):
    parsed = raw.split(".")
    if len(parsed) != 3:
        raise RuntimeError("Bad version " + raw)
    return map(int, parsed)
    
def compare_versions(v1, v2):
    cv1 = list(v1)
    cv2 = list(v2)
    if len(v1) == 0 and len(v2) == 0:
        return 0
    res = cv1.pop(0) - cv2.pop(0)
    if res != 0:
        return res
    else:
        return compare_versions(cv1, cv2)

def version_to_str(version):
    return ".".join(map(str,version))
    
def touch(file_path):
    open(file_path, "a").close()

def get_versions(client, name):
    stdin, stdout, stderr = client.exec_command("ls -lh %s/%s | awk '{print $9}'" %(REPOSITORY_PATH, name))
    allv = map(parse_version, get_substance(stdout.readlines()))
    allv.sort(compare_versions)
    return allv

def parse_nanny_lines(client, substancelines):
    def parse_dep(dep):
        raw = dep.split()
        if len(raw)==1:
            return (raw[0], None)
        else:
            return (raw[0], parse_version(raw[1]))
    ret =  dict(map(parse_dep, substancelines))
    for name, v in ret.items():
        allv = get_versions(client, name)
        if len(allv)==0:
            raise RuntimeError("Dependency not found " + name)
        if v is None:
            v = allv[-1]
            ret[name] = v
        if v not in allv:
            raise RuntimeError("Invalid version %s for dependency %s", (version_to_str(v), name))
    return ret
    
def parse_nanny_file(client, filename):
    deps_raw = get_substance_lines(filename)
    return parse_nanny_lines(client, deps_raw)
    
def versions(client, args):
    print "Getting versions for " + args[0] + ":\n"
    allv = map(version_to_str, get_versions(client, args[0]))
    if len(allv) == 0:
        print "Dependency not found"
    else:
        for v in allv:
            print v

def pull(client, remote, local, ignore_error = False):
    ftp = client.open_sftp()
    try:
        ftp.get(remote, local)
    except IOError, e:
        if not ignore_error:
            raise e
    finally:
        ftp.close()

def put(client, local, remote):
    ftp = client.open_sftp()
    try:
        ftp.put(local, remote)
    finally:
        ftp.close()
        
def remote_mkdir(client, path):
    ftp = client.open_sftp()
    try:
        ftp.mkdir(path)
    except IOError, e:
        pass
        #print "Warning..." + str(e)
    finally:
        ftp.close()

def remote_rename(client, source, target):
    ftp = client.open_sftp()
    try:
        ftp.rename(source, target)
    finally:
        ftp.close()

def install_dep(client, name, version):
    #download dep, uninstall, read in deps NANNY file (if exists) install those deps
    #detect circularity?
    allv = get_versions(client, name)
    if len(allv)==0:
        raise RuntimeError("Dependency not found " + name)
    if version is None:
        version = allv[-1]
    if version not in allv:
        raise RuntimeError("Invalid version %s for dependency %s", (version_to_str(version), name))
    print "Downloading version %s of %s:" % (version_to_str(version), name)
    install_path = "_deps/_actual/" + name + "-" + version_to_str(version)
    os.mkdir(install_path)
    
    version_path = "%s/%s/%s" %(REPOSITORY_PATH, name, version_to_str(version))
    pull(client, version_path + "/dep.tar.gz", install_path + "/dep.tar.gz")
    os.system("cd " + install_path + " && tar xzf dep.tar.gz")
    os.remove(install_path + "/dep.tar.gz")
    os.symlink("_actual/" + name + "-" + version_to_str(version), "_deps/" + name)

def get_deps(client, name, version, depsmap):
    remote_path = REPOSITORY_PATH + "/" + name + "/" + version_to_str(version)
    stdin, stdout, stderr = client.exec_command("cat %s/NANNY" % remote_path)
    new_deps = parse_nanny_lines(client, stdout.readlines())    
    print name + " has dependencies " + str(new_deps)
    for dep, v in new_deps.items():
        if dep in depsmap:
            currv = depsmap[dep]
            if currv != v:
                print "Warning: Conflicting versions of %s, %s and %s. Choosing more recent version" % (dep, version_to_str(currv), version_to_str(v))
                if compare_versions(currv, v) > 0:
                    v = currv
        depsmap[dep] = v
    for dep, v in new_deps.items():
        get_deps(client, dep, v, depsmap)

def get_all_deps(client, nanny_file):
    deps = parse_nanny_file(client, nanny_file)
    for name, version in deps.items():
        get_deps(client, name, version, deps)
    return deps

def deps(client, args):
    shutil.rmtree("_deps", ignore_errors=True)
    os.mkdir("_deps")    
    os.mkdir("_deps/_actual")
    touch("_deps/__init__.py")
    deps = get_all_deps(client, "NANNY")
    
    print "All deps:"
    for name, version in deps.items():
        print "\t%s\t%s" % (name, version_to_str(version))
    
    for name, version in deps.items():
        install_dep(client, name, version)
    if os.path.exists("project.clj"):
        os.system("lein deps")
    

def get_child_info(file_path):
    lines = get_substance_lines(file_path)
    def parse_pair(s):
        pair = s.split()
        if len(pair) > 2: raise RuntimeError("Bad child pair")
        if len(pair) == 1:
            pair = [pair[0], "CHILDMAKER"]
        return pair
    return dict(map(parse_pair, lines))

def remote_version(client, args):
    pairs = get_child_info("CHILD")
    for name, _ in pairs.items():
        curr_versions = get_versions(client, name)
        if len(curr_versions) == 0:
            print "'%s' does not exist in the repository" % name
        else:
            print name + ": " + version_to_str(curr_versions[-1])

def list_available(client, args):
    alldeps = get_substance(client.exec_command("ls -lh %s | awk '{print $9}'" % REPOSITORY_PATH)[1].readlines())
    #TODO: show all the version #'s too
    for dep in alldeps:
        print dep

def print_help(client, args):
    print "Available commands:"
    print ""
    print "deps: Download all dependencies listed in NANNY file and write them to _deps/ folder. This command"
    print "\twill delete the _deps folder before running."
    print ""
    print "push [childname] {major.minor.revision}: Upload a new version of this child. {childname} is optional,"
    print "\tyou only need to specify it if your CHILD file has multiple entries."
    print ""
    print "remote-version: List the current version in the repository of the children from this package."
    print ""
    print "list: Print all children available in the repository for installing as dependencies"
    print ""
    print "versions {childname}: Print the versions available for {childname} in the repository"
    print ""
    print "help: Print this message"
    print ""
    print ""

def push(client, args):
    child_pairs = get_child_info("CHILD")
    if len(args) == 1:
        if len(child_pairs) != 1:
            raise RuntimeError("Invalid args")
        name = child_pairs.items()[0][0]
        version = parse_version(args[0])
    else:
        name = args[0]
        version = parse_version(args[1])
    makerscript = child_pairs[name]
    curr_versions = get_versions(client, name)
    if len(curr_versions) > 0 and compare_versions(curr_versions[-1], version) >= 0:
        raise RuntimeError("Cannot deploy a less than or equal version than current version " +
                        version_to_str(curr_versions[-1]))
    
    shutil.rmtree("/tmp/_nanny", ignore_errors=True)
    os.mkdir("/tmp/_nanny")
    os.system("./%s /tmp/_nanny/" % makerscript)
    
    remote_mkdir(client, REPOSITORY_PATH + "/" + name)
    remote_tmp_path = "/tmp/_nanny-" + name
    client.exec_command("rm -rf " + remote_tmp_path)
    remote_mkdir(client, remote_tmp_path)
    
    if os.path.exists("/tmp/_nanny/NANNY"):
        put(client, "/tmp/_nanny/NANNY", remote_tmp_path + "/NANNY")
        os.remove("/tmp/_nanny/NANNY")        
    elif os.path.exists("NANNY"):
        put(client, "NANNY", remote_tmp_path + "/NANNY")

    os.system("cd /tmp/_nanny && tar czf dep.tar.gz *")
    put(client, "/tmp/_nanny/dep.tar.gz", remote_tmp_path + "/dep.tar.gz")

    remote_path = "%s/%s/%s" % (REPOSITORY_PATH, name, version_to_str(version))
    client.exec_command("mv %s %s" % (remote_tmp_path, remote_path))


commands = {"deps": deps, "remote-version": remote_version, "push": push, 
            "versions": versions, "list": list_available, "help": print_help}
sys.argv.pop(0) #remove filename
command = None
if len(sys.argv) > 0:
    command = sys.argv.pop(0)
if command is None or command not in commands:
    command = "help"

try:
    if command=="help":
        client = None
    else:
        client = SSHClient()
        client.load_system_host_keys()
        client.connect(REPOSITORY_HOST, username=REPOSITORY_USER)
    
    commands[command](client, sys.argv)
    if command != "help":
        print ""
        print command + " [SUCCESSFUL]"
finally:
    if client is not None:
        client.close()