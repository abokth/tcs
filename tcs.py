#!/usr/bin/env python
# -*- coding: utf8 -*- 
#
# Copyright (C) 2012 Peter Reuterås
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by 
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.                                                                                                                            
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import ConfigParser
import MySQLdb
import argparse
import ldap
import re
import sys

# Class used with argparse to store arguments.
class Opts(object):
    pass

# Validate that all users in the database are still in the allowed group
# ug_users         = users in ldap/UG
# stored_users     = users in database
# return: string with report of validation or '' if ok
def validate_in_ug_group(ug_users, stored_users):
    local_report = ''
    for user in stored_users:
        if not user in ug_users:
            local_report += "User: %s is no longer in the group.\n" % user
    return local_report

# Get users that are allowed to get certs
# lc                = ldap connection
# return: list of users that are allowed to get certs
def get_ug_users(lc):
    result = lc.search_s('ou=groups,ou=UG,dc=kth,dc=se',ldap.SCOPE_SUBTREE,'(cn=app.tcs.id)',['ugMemberKthid'])
    return result[0][1]['ugMemberKthid']

# Get users that have been allowed to get certs
# dbc               = database connection
# return: list of users stored in the database
def get_stored_users(dbc):
    users = []
    dbc.execute ("SELECT ugkthid FROM tcsusers")
    while (1):
        row = dbc.fetchone ()
        if row == None:
            break
        users.append(row[0])
    return users

# Check that the user is in the database, otherwise add the user
# dbc               = database connection
# ugkthid           = ugkthid from ldap (unique user number)
# eppa              = affiliation from ldap
# givenname         = firstname from ldap
# sn                = lastname from ldap
# return: string with report of validation or '' if ok
def check_in_database(dbc, ugkthid, eppa, givenname, sn):
    local_report = ''
    dbc.execute ("SELECT ugkthid, eppa, givenname, sn FROM tcsusers WHERE ugkthid = '%s'" % ugkthid)
    row = dbc.fetchone ()
    if row == None:
        dbc.execute ("""
            INSERT INTO tcsusers (ugkthid, eppa, givenname, sn)
            VALUES
            ('%s', '%s', '%s', '%s')""" % (ugkthid, eppa, givenname, sn))
    return local_report

# Make sure the affiliation is staff or student
# temporary allow other
# Note: This is the only two affiliations we have that are allowed to get
# certs. This might differ for other universities.
# eppa              = affiliation from ldap
# ugkthid           = ugkthid from ldap (unique user number)
# return: string with report of validation or '' if ok
def check_affiliation(eppa, ugkthid):
    local_report = ''
    if eppa != "staff" and eppa != "student" and eppa != "other":
        local_report = "User: %s now have affiliation %s.\n" % (ugkthid, eppa)
    return local_report

# Check if the user has changed his/her name
# dbc               = database connection
# ugkthid           = ugkthid from ldap (unique user number)
# givenname         = firstname from ldap
# sn                = lastname from ldap
# return: string with report of validation or '' if ok
def check_name(dbc, ugkthid, givenname, sn):
    local_report = ''
    dbc.execute ("SELECT givenname, sn FROM tcsusers WHERE ugkthid = '%s'" % ugkthid)
    row = dbc.fetchone ()
    if row == None:
        return "Could not check name for user %s.\n" % ugkthid
    if unicode(givenname) != row[0] or sn != row[1]:
        return "User: %s has changed name. In UG: %s, %s and in DB: %s, %s\n" % (ugkthid, givenname, sn, row[0], row[1])
    return local_report

# Init configuration
# configFile        = configuration file name
# return: configParser object with configuration                       
def configuration_init(configFile):
    configuration = ConfigParser.RawConfigParser()
    configuration.read(configFile)
    return configuration

# Init ldap configuration
# configuration     = configParser object with configuration
# return: ldap server connection                    
def ldap_init(configuration):
    ldap_server = configuration.get('ldap', 'server')
    ldap_username = configuration.get('ldap', 'username')
    ldap_password  = configuration.get('ldap', 'password')

    lc = ldap.initialize(ldap_server)
    lc.simple_bind(ldap_username, ldap_password)

    return lc

# Init mysql configuration
# configuration     = configParser object with configuration
# return: mysql server connection                    
def mysql_init(configuration):
    mysql_server = configuration.get('mysql', 'server')
    mysql_username = configuration.get('mysql', 'username')
    mysql_password = configuration.get('mysql', 'password')
    mysql_database = configuration.get('mysql', 'database')

    try:
        db = MySQLdb.connect(mysql_server,
            mysql_username,
            mysql_password,
            mysql_database,
            use_unicode=True)
        db.set_character_set('utf8')
        dbc = db.cursor ()
        dbc.execute('SET NAMES utf8;')
        dbc.execute('SET CHARACTER SET utf8;')
        dbc.execute('SET character_set_connection=utf8;')
    except MySQLdb.Error, e:
        print "Error %d: %s" % (e.args[0], e.args[1])
        sys.exit(1)

    return dbc

# Get user info from ldap/UG
# lc                = ldap connection
# ugkthid           = ugkthid from ldap (unique user number)
# return: data from ldap
#  ugkthid = uniq identifier of user
#  givenname = firstname
#  sn = lastname
#  eppa = edupersonprimaryaffiliation ("staff", "student" or "")
def getUserInfo(lc, ugkthid):
    result = lc.search_s('ou=People,ou=UG,dc=kth,dc=se',ldap.SCOPE_SUBTREE,'(ugKthid=%s)' % ugkthid,['sn', 'givenName', 'eduPersonPrimaryAffiliation', 'ugKthid'])
    ugkthid = result[0][1]['ugKthid'][0]
    givenname = unicode(result[0][1]['givenName'][0].decode('iso-8859-1'))
    sn = unicode(result[0][1]['sn'][0].decode('iso-8859-1'))
    eppa = result[0][1]['eduPersonPrimaryAffiliation'][0]
    return (ugkthid, givenname, sn, eppa)


# For each user call validation functions                                        
# lc                = ldap connection
# dbc               = database connection
# ug_users          = users in ldap/UG
# return: string with report of validation or '' if ok
def validate_each_user(dbc, lc, ug_users):
    local_report = ''
    for user in ug_users:
        (ugkthid, givenname, sn, eppa) = getUserInfo(lc, user)
        local_report += check_in_database(dbc, ugkthid, eppa, givenname, sn)
        local_report += check_affiliation(eppa, ugkthid)
        local_report += check_name(dbc, ugkthid, givenname, sn)

    return local_report

# Main validate function that calls other validation functions
# lc                = ldap connection
# dbc               = database connection
# return: True and output report to stdout
def validate(lc, dbc):
    report = ''

    ug_users = get_ug_users(lc)

    if ug_users == []:
        print "No users in group app.tcs.id. Exiting"
        sys.exit(1)

    stored_users = get_stored_users(dbc)

    report += validate_in_ug_group(ug_users, stored_users)

    report += validate_each_user(dbc, lc, ug_users)

    print "Report for TCS"
    print "=============="
    print ""
    if report != '':
        print report
    else:
        print "Nothing to report."
        print ""
    print "End of report"
    return True

# Validate a ugkthid
# lc                = ldap connection
# dbc               = database connection
# ugkthid           = ugkthid from ldap (unique user number)
# return: True or halt on failure               
def valid_ugkthid(ugkthid):
    if re.search(r'^u1[a-z0-9]{6}$', ugkthid):
        return True
    else:
        print "Not a valid ugkthid: %s" % ugkthid
        sys.exit(1)

# Remove user ugkthid from database                   
# lc                = ldap connection
# dbc               = database connection
# ugkthid           = ugkthid from ldap (unique user number)
# return: True or halt on failure               
def removeUserDB(dbc, ugkthid):
    stored_users = get_stored_users(dbc)
    if ugkthid in stored_users:
        dbc.execute ("DELETE FROM tcsusers WHERE ugkthid = '%s' LIMIT 1" % ugkthid)
        return True
    else:
        print "User: %s not in db" % ugkthid
        sys.exit(1)

# Update user ugkthid in the database
# lc                = ldap connection
# dbc               = database connection
# ugkthid           = ugkthid from ldap (unique user number)
# return: True or halt on failure               
def updateUserDB(lc, dbc, ugkthid):
    stored_users = get_stored_users(dbc)
    if ugkthid in stored_users:
        (ugkthid, givenname, sn, eppa) = getUserInfo(lc, ugkthid)
        dbc.execute ("""UPDATE tcsusers 
                SET givenname='%s', sn='%s', eppa='%s' 
                WHERE ugkthid = '%s'""" % (givenname, sn, eppa, ugkthid))
        print "User: %s updated to %s, %s, %s" % (ugkthid, givenname, sn, eppa)
        return True                                                                               
    else:
        print "User: %s not in db" % ugkthid
        sys.exit(1)

# Check if we can delete user from db and if so call function to do it.                   
# lc                = ldap connection
# dbc               = database connection
# ugkthid           = ugkthid from ldap (unique user number)
# return: True or halt on failure               
def remove(lc, dbc, ugkthid):
    ug_users = get_ug_users(lc)
    valid_ugkthid(ugkthid)
    if not ugkthid in ug_users:
        removeUserDB(dbc, ugkthid)
    else:
         print "User: %s still in UG-group. Remove there first." % ugkthid
         sys.exit(1)
    return True

# Check if user is in ug group and it is a valid u1. If so call function to
# update db.
# lc                = ldap connection
# dbc               = database connection
# ugkthid           = ugkthid from ldap (unique user number)
# return: True or halt on failure               
def update(lc, dbc, ugkthid):
    ug_users = get_ug_users(lc)
    valid_ugkthid(ugkthid)
    if ugkthid in ug_users:
        updateUserDB(lc, dbc, ugkthid)
    else:
        print "User: %s not in UG-group. Add them there first." % ugkthid
        sys.exit(1)
    return True

# main function
def main():
    options = Opts()
    parser = argparse.ArgumentParser(description='TCS admin tool.')
    parser.add_argument('-c',
        help="Specify configuration file", default='tcs.cfg', dest="configFile")
    parser.add_argument("-v", action="store_true", dest="validateUser",
        help="Validate users", default=False)
    parser.add_argument("-r", action="store_true", dest="removeUser",
        help="Remove user", default=False)
    parser.add_argument("-u", action="store_true", dest="updateUser",
        help="Update user", default=False)
    parser.add_argument('User', nargs='?')
    parser.parse_args(namespace=options)

    if options.validateUser and options.removeUser:
        print "Use only one of -v -u"
        sys.exit(1)

    configuration = configuration_init(options.configFile)
    lc = ldap_init(configuration)

    dbc = mysql_init(configuration)

    if options.validateUser:
        validate(lc, dbc)
    elif not options.User:
        print "Must specify one user"
    elif options.removeUser:
        remove(lc, dbc, options.User)
    elif options.updateUser:
        update(lc, dbc, options.User)

if __name__ == '__main__':
    main()

