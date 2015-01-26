#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Deployment script that will deploy Postgres schemas to a given DB
Copyright (c) Affinitas GmbH

Usage:
  dpm.py deploy <connection_string> [-m | --mode <mode>]
                [-o | --owner <owner_role>] [-u | -user <user_role>...] 
                [-f | --file <file_name>...]
  dpm.py -h | --help
  dpm.py -v | --version
  
Arguments:
  <connection_string>       Connection string to postgres database. 
                            Can be in any format psycopg2 would understand it
  
Options:
  -h --help                 Show this screen.
  -v --version              Show version.
  -p --production           Add constraints to deployment. Will not deploy versioned schema 
                            if it already exists in the DB
  -f <file_name>..., --file <file_name>...      
                            Use it if you want to deploy only specific files (functions, types, etc). 
                            In that case these files if exist will be overriden. 
                            Should be followed by the list of names of files to deploy.
  -o <owner_role>, --owner <owner_role>         
                            Role to which schema owner will be changed. User connecting to DB 
                            needs to be a superuser. If ommited, user running the script 
                            will the owner of schema
  -u <user_role>..., -user <user_role>...       
                            Roles to which GRANT USAGE privelage will be applied. 
                            If ommited, default behaviour of DB applies
  -m <mode>, --mode <mode>  Deployment mode. Can be:
                            - safe. Add constraints to deployment. Will not deploy schema 
                            if it already exists in the DB
                            - moderate. If schema exists, will try to rename it by adding suffix "_"
                            and deploy new schema with old name
                            - unsafe. allows cascade deleting of schema if it exists and adding new one
                            [default: safe]

"""

import os
import psycopg2
import json
import sqlparse
import re
from dpm import _version
from pprint import pprint
from docopt import docopt

def close_db_conn(cur, conn, conn_string):
    """
    Close DB connection and cursor
    """
    print('\nClosing connection to {0}...'.format(conn_string))
    cur.close()
    conn.close()
    print('Connection to {0} closed.'.format(conn_string))

def create_db_schema(cur, schema_name, users, owner):
    """
    Create Postgres schema script and execute it on cursor
    """
    _create_schema_script = "\nCREATE SCHEMA " + schema_name + " ;\n"
    _create_schema_script += "GRANT USAGE ON SCHEMA " + schema_name + " TO " + users + ";\n"
    _create_schema_script += "ALTER SCHEMA " + schema_name + " OWNER TO " + owner + ";\n"
    _create_schema_script += "SET search_path TO " + schema_name + ", public;"
    cur.execute(_create_schema_script)
    print('Schema {0} was created and search_path was changed. The following script was executed: {1}'.format(schema_name, _create_schema_script))

def find_whole_word(w):
    """
    Finds whole word
    """
    return re.compile(r'\b({0})\b'.format(w), flags=re.IGNORECASE).search

def main():
    arguments = docopt(__doc__, version = _version.__version__)
    if arguments['deploy']:
        # Load project configuration file
        print('\nLoading project configuration...')
        config_json = open('config.json')
        config_data = json.load(config_json)
        print('Configuration of project {0} of version {1} loaded successfully.'.format(config_data['name'], config_data['version']))
        config_json.close()

        # Get types files and calculate order of execution
        if config_data['types_path']:
            types_path = config_data['types_path']
        else:
            types_path = "types"

        print('\nGetting scripts with types definitions')
        types_files_count = 0
        types_script = ''
        for subdir, dirs, files in os.walk(types_path):
            for file in files:
                if arguments['--file']: # if specific script to be deployed, only find them
                    for list_file_name in arguments['--file']:
                        if file == list_file_name:
                            types_files_count += 1
                            types_script += open(os.path.join(subdir, file), 'r', -1, 'UTF-8').read()
                            types_script += '\n'
                            print('{0}'.format(os.path.join(subdir, file)))
                else: # if the whole schema to be deployed
                    types_files_count += 1
                    types_script += open(os.path.join(subdir, file), 'r', -1, 'UTF-8').read()
                    types_script += '\n'
                    print('{0}'.format(os.path.join(subdir, file)))
        if types_files_count == 0:
            print('No types definitions were found in {0} folder'.format(types_path))

        # Get functions scripts
        if config_data['functions_path']:
            functions_path = config_data['functions_path']
        else:
            functions_path = "functions"

        print('\nGetting scripts with functions definitions')
        functions_files_count = 0
        functions_script = ''
        for subdir, dirs, files in os.walk(functions_path):
            for file in files:
                if arguments['--file']: # if specific script to be deployed, only find them
                    for list_file_name in arguments['--file']:
                        if file == list_file_name:
                            functions_files_count += 1
                            functions_script += open(os.path.join(subdir, file), 'r', -1, 'UTF-8').read()
                            functions_script += '\n'
                            print('{0}'.format(os.path.join(subdir, file)))
                else: # if the whole schema to be deployed
                    functions_files_count += 1
                    functions_script += open(os.path.join(subdir, file), 'r', -1, 'UTF-8').read()
                    functions_script += '\n'
                    print('{0}'.format(os.path.join(subdir, file)))
        if functions_files_count == 0:
            print('No functions definitions were found in {0} folder'.format(functions_path))


        # Connect to DB
        print('\nConnecting to databases for deployment...')
        try:
            conn = psycopg2.connect(arguments['<connection_string>'])
            cur = conn.cursor()
        except psycopg2.Error as e:
            exit('Connection to DB failed ', e)
        print('Connected to ', arguments['<connection_string>'])

        # Prepare and execute preamble
        _deploymeny_script_preamble = "--\n"            \
            "-- Start of composed deployment script\n"  \
            "-- \n"                                     \
            "SET statement_timeout = 0;\n"              \
            "SET client_encoding = 'UTF8';\n"           \
            "SET standard_conforming_strings = off;\n"  \
            "SET check_function_bodies = false;\n"      \
            "SET client_min_messages = warning;\n"      \
            "SET escape_string_warning = off;\n"
        print('Executing a preamble to deployment statement')
        print(_deploymeny_script_preamble)
        cur.execute(_deploymeny_script_preamble)

        # Get schema name from project configuration
        schema_name = ''
        if config_data['subclass'] == 'versioned':
            schema_name = '{0}_{1}'.format(config_data['name'], config_data['version'])
            print('Schema {0} will be updated'.format(schema_name))
        elif config_data['subclass'] == 'non-versioned':
            schema_name = '{0}'.format(config_data['name'])
            print('Schema {0} will be created/replaced'.format(schema_name))

        # Create schema or update it if exists (if not in production mode) and set search path
        cur.execute("SELECT EXISTS (SELECT schema_name FROM information_schema.schemata WHERE schema_name = %s);", (schema_name,))
        schema_exists = cur.fetchone()[0]
        if arguments['--file']: # if specific scripts to be deployed
            if not schema_exists:
                print('Can\'t deploy scripts to schema {0}. Schema doesn\'t exist in database'.format(schema_name))
                close_db_conn(cur, conn, arguments.get('<connection_string>'))
                exit()
            else:
                _set_search_path_schema_script = "SET search_path TO " + schema_name + ", public;"
                cur.execute(_set_search_path_schema_script)
                print('Search_path was changed to schema {0}. The following script was executed: {1}'.format(schema_name, _set_search_path_schema_script))
        else:
            if not schema_exists:
                create_db_schema(cur, schema_name, ", ".join(config_data['user_role']), config_data['owner_role'])
            elif arguments['--production'] == 1:
                print('Schema already exists. It won\'t be overriden in production mode. Rerun your script without -p or --production flag')
                close_db_conn(cur, conn, arguments.get('<connection_string>'))
                exit()
            else:
                _drop_schema_script = "\nDROP SCHEMA " + schema_name + " CASCADE;\n"
                cur.execute(_drop_schema_script)
                print('Droping old schema {0}'.format(schema_name))
                create_db_schema(cur, schema_name, ", ".join(config_data['user_role']), config_data['owner_role'])

        # Reordering and executing types
        if types_files_count > 0:
            if arguments['--file']:
                print('Deploying types definition scripts in existing schema without droping it first is not support yet. Skipping')
            else:
                print('Running types definitions scripts')
                print('Reordering types definitions scripts to avoid "type does not exist" exceptions')
                _type_statements = sqlparse.split(types_script)
                _type_statements_dict = {} # dictionary that store statements with type and order. TODO: move up to classes
                type_unordered_scripts = [] #scripts to execute without order
                for _type_statement in _type_statements:
                    _type_statement_parsed = sqlparse.parse(_type_statement)
                    if len(_type_statement_parsed) > 0: # can be empty parsed object so need to check
                        if _type_statement_parsed[0].get_type() == 'CREATE': # we need only type declarations to be ordered
                            for _type_statement_token in _type_statement_parsed[0].tokens:
                                if _type_statement_token.ttype == None: # if it's not a keyword (that's how it's defined in sqlparse)
                                    _type_body_part_counter = 0 # we need counter cause we know that first entrance is the name of the type
                                    for _type_body_part in _type_statement_token.flatten():
                                        if not _type_body_part.is_whitespace():
                                            if _type_body_part_counter == 0:
                                                _type_statements_dict[str(_type_body_part)] = {'script': _type_statement, 'deps': []}
                                            _type_body_part_counter += 1
                        else:
                            type_unordered_scripts.append(_type_statement)
                # now let's add dependant types to dictionary with types
                _type_statements_list = [] # list of statements to be ordered
                for _type_key in _type_statements_dict.keys():
                    for _type_key_sub, _type_value in _type_statements_dict.items():
                        if _type_key != _type_key_sub:
                            if find_whole_word(_type_key)(_type_value['script']):
                                _type_value['deps'].append(_type_key)
                # now let's add order to type scripts and put them orsered to list
                _deps_unresolved = True
                _type_script_order = 0
                _type_names = []
                type_ordered_scripts = [] # ordered list with scripts to execute
                while _deps_unresolved:
                    for k, v in _type_statements_dict.items():
                        if v['deps'] == []:
                            _type_names.append(k)
                            v['order'] = _type_script_order
                            _type_script_order += 1
                            if not v['script'] in type_ordered_scripts:
                                type_ordered_scripts.append(v['script'])
                        else:
                            _dep_exists = True
                            for _dep in v['deps']:
                                if not _dep in _type_names:
                                    _dep_exists = False
                            if _dep_exists:
                                _type_names.append(k)
                                v['order'] = _type_script_order
                                _type_script_order += 1
                                if not v['script'] in type_ordered_scripts:
                                    type_ordered_scripts.append(v['script'])
                            else:
                                v['order'] = -1
                    _deps_unresolved = False
                    for k, v in _type_statements_dict.items():
                        if v['order'] == -1:
                            _deps_unresolved = True

                #print('\n'.join(type_ordered_scripts)) # uncomment for debug
                if type_ordered_scripts:
                    cur.execute('\n'.join(type_ordered_scripts))
                #print('\n'.join(type_unordered_scripts)) # uncomment for debug
                if type_unordered_scripts:
                    cur.execute('\n'.join(type_unordered_scripts))
                print('Types loaded to schema {0}'.format(schema_name))
        else:
            print('No type scripts to deploy')

        # Executing functions
        if functions_files_count > 0:
            print('Running functions definitions scripts')
            cur.execute(functions_script)
            print('Functions loaded to schema {0}'.format(schema_name))
        else:
            print('No function scripts to deploy')

        # Commit transaction
        conn.commit()

        close_db_conn(cur, conn, arguments.get('<connection_string>'))

    else:
        print(arguments)

if __name__ == '__main__':
    main()