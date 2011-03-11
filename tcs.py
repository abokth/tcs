#!/usr/bin/env python

import ConfigParser
import MySQLdb
import argparse
import ldap
import re
import sys

class Opts(object):
    pass

def validate_in_ug_group(ug_users, stored_users):
    local_report = ''
    for user in stored_users:
        if not user in ug_users:
            local_report += "User: %s is no longer in the group.\n" % user
    return local_report

def get_ug_users(l):
    result = l.search_s('ou=groups,ou=UG,dc=kth,dc=se',ldap.SCOPE_SUBTREE,'(cn=app.tcs.id)',['ugMemberKthid'])
    return result[0][1]['ugMemberKthid']

def get_stored_users(dbc):
    users = []
    dbc.execute ("SELECT ugkthid FROM tcsusers")
    while (1):
        row = dbc.fetchone ()
        if row == None:
            break
        users.append(row[0])
    return users
    
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

def check_affiliation(eppa, ugkthid):
    local_report = ''
    if eppa != "staff" and eppa != "student":
        local_report = "User: %s now have affiliation %s.\n" % (ugkthid, eppa)
    return local_report
    
def check_name(dbc, ugkthid, givenname, sn):
    local_report = ''
    dbc.execute ("SELECT givenname, sn FROM tcsusers WHERE ugkthid = '%s'" % ugkthid)
    row = dbc.fetchone ()
    if row == None:
        return "Could not check name for user %s.\n" % ugkthid
    if unicode(givenname) != row[0] or sn != row[1]:
        return "User: %s has changed name. In UG: %s, %s and in DB: %s, %s" % (ugkthid, givenname, sn, row[0], row[1])
    return local_report

def configuration_init(configFile):
    configuration = ConfigParser.RawConfigParser()
    configuration.read(configFile)
    return configuration 

def ldap_init(configuration):
    ldap_server = configuration.get('ldap', 'server')
    ldap_username = configuration.get('ldap', 'username')
    ldap_password  = configuration.get('ldap', 'password')

    lc = ldap.initialize(ldap_server)
    lc.simple_bind(ldap_username, ldap_password)

    return lc

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

def getUserInfo(lc, user):
    result = lc.search_s('ou=People,ou=UG,dc=kth,dc=se',ldap.SCOPE_SUBTREE,'(ugkthid=%s)' % user,['sn', 'givenName', 'eduPersonPrimaryAffiliation', 'ugkthid'])
    ugkthid = result[0][1]['ugkthid'][0]
    givenname = unicode(result[0][1]['givenName'][0].decode('iso-8859-1'))
    sn = unicode(result[0][1]['sn'][0].decode('iso-8859-1'))
    eppa = result[0][1]['eduPersonPrimaryAffiliation'][0]
    return (ugkthid, givenname, sn, eppa)


def validate_each_user(dbc, lc, ug_users):
    local_report = ''
    for user in ug_users:
        (ugkthid, givenname, sn, eppa) = getUserInfo(lc, user)
        local_report += check_in_database(dbc, ugkthid, eppa, givenname, sn)
        local_report += check_affiliation(eppa, ugkthid)
        local_report += check_name(dbc, ugkthid, givenname, sn)

    return local_report

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

def valid_u1(u1):
    if re.search(r'^u1[a-z0-9]{6}$', u1):
        return True
    else:
        print "Not a valid u1: %s" % u1
        sys.exit(1)

def removeUserDB(dbc, user):
    stored_users = get_stored_users(dbc)
    if user in stored_users:
        dbc.execute ("DELETE FROM tcsusers WHERE ugkthid = '%s' LIMIT 1" % user)
    else:
        print "User: %s not in db" % user
        sys.exit(1)

def updateUserDB(lc, dbc, u1):
    stored_users = get_stored_users(dbc)
    if u1 in stored_users:
        (ugkthid, givenname, sn, eppa) = getUserInfo(lc, u1)
        dbc.execute ("""UPDATE tcsusers 
                SET givenname='%s', sn='%s', eppa='%s' 
                WHERE ugkthid = '%s'""" % (givenname, sn, eppa, u1))
        print "User: %s updated to %s, %s, %s" % (u1, givenname, sn, eppa)
    else:
        print "User: %s not in db" % user
        sys.exit(1)

def remove(lc, dbc, u1):
    ug_users = get_ug_users(lc)
    valid_u1(u1)
    if not u1 in ug_users:
        removeUserDB(dbc, u1)
    else:
         print "User: %s still in UG-group. Remove there first." % u1
         sys.exit(1)
    return True

def update(lc, dbc, u1):
    ug_users = get_ug_users(lc)
    valid_u1(u1)
    if u1 in ug_users:
        updateUserDB(lc, dbc, u1)
    else:
        print "User: %s not in UG-group. Add them there first." % u1
        sys.exit(1)
    return True

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
    elif options.removeUser:
        remove(lc, dbc, options.User)
    elif options.updateUser:
        update(lc, dbc, options.User)

if __name__ == '__main__':
    main()

