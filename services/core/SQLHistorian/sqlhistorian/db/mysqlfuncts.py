# -*- coding: utf-8 -*- {{{
# vim: set fenc=utf-8 ft=python sw=4 ts=4 sts=4 et:

# Copyright (c) 2013, Battelle Memorial Institute
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in
#    the documentation and/or other materials provided with the
#    distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#
# The views and conclusions contained in the software and documentation
# are those of the authors and should not be interpreted as representing
# official policies, either expressed or implied, of the FreeBSD
# Project.
#
# This material was prepared as an account of work sponsored by an
# agency of the United States Government.  Neither the United States
# Government nor the United States Department of Energy, nor Battelle,
# nor any of their employees, nor any jurisdiction or organization that
# has cooperated in the development of these materials, makes any
# warranty, express or implied, or assumes any legal liability or
# responsibility for the accuracy, completeness, or usefulness or any
# information, apparatus, product, software, or process disclosed, or
# represents that its use would not infringe privately owned rights.
#
# Reference herein to any specific commercial product, process, or
# service by trade name, trademark, manufacturer, or otherwise does not
# necessarily constitute or imply its endorsement, recommendation, or
# favoring by the United States Government or any agency thereof, or
# Battelle Memorial Institute. The views and opinions of authors
# expressed herein do not necessarily state or reflect those of the
# United States Government or any agency thereof.
#
# PACIFIC NORTHWEST NATIONAL LABORATORY
# operated by BATTELLE for the UNITED STATES DEPARTMENT OF ENERGY
# under Contract DE-AC05-76RL01830
#}}}

import errno
import logging
import os

from mysql import connector
from zmq.utils import jsonapi

from basedb import DbDriver
from volttron.platform.agent import utils

utils.setup_logging()
_log = logging.getLogger(__name__)

class MySqlFuncts(DbDriver):

    def __init__(self, **kwargs):
        _log.debug("Constructing MySqlFuncts")
        super(DbDriver, self).__init__(**kwargs)
        self.__connect_params = kwargs
        
        if not kwargs.get('user', None):
            raise AttributeError('Invalid parameter for "user" specified!')
        if not kwargs.get('passwd', None):
            raise AttributeError('Invalid parameter for "passwd" specified!')
        if not kwargs.get('database', None):
            raise AttributeError('Invalid "database" specified!')
        
        try:
            if not self.__check_connection():
                raise AttributeError(
                        "Couldn't connect using specified configuration" 
                        " credentials")
        except connector.errors.ProgrammingError:
            raise AttributeError("Couldn't connect using specified " 
                        "configuration credentials")
            
    def __check_connection(self):
        can_connect = False
        
        conn = connector.connect(**self.__connect_params)
        
        if conn:
            can_connect = conn.is_connected()        
        else:
            raise AttributeError("Could not connect to specified mysql " 
                                 "instance.")
        if can_connect:
            conn.close()
        
        return can_connect

    def __connect(self):
        
        conn = connector.connect(**self.__connect_params)
        # enable transactions here.
        conn.autocommit=False
        
        return conn
    
    def query(self, topic, start=None, end=None, skip=0,
                            count=None, order="FIRST_TO_LAST"):
        """This function should return the results of a query in the form:
        {"values": [(timestamp1, value1), (timestamp2, value2), ...],
         "metadata": {"key1": value1, "key2": value2, ...}}

         metadata is not required (The caller will normalize this to {} for you)
        """
        query = '''SELECT data.ts, data.value_string
                   FROM data, topics
                   {where}
                   {order_by}
                   {limit}
                   {offset}'''

        where_clauses = ["WHERE topics.topic_name = %s", "topics.topic_id = data.topic_id"]
        args = [topic]

        if start is not None:
            where_clauses.append("data.ts > %s")
            args.append(start)

        if end is not None:
            where_clauses.append("data.ts < %s")
            args.append(end)

        where_statement = ' AND '.join(where_clauses)

        order_by = 'ORDER BY data.ts ASC'
        if order == 'LAST_TO_FIRST':
            order_by = ' ORDER BY data.ts DESC'

        #can't have an offset without a limit
        # -1 = no limit and allows the user to
        # provied just an offset
        if count is None:
            count = 100

        limit_statement = 'LIMIT %s'
        args.append(count)

        offset_statement = ''
        if skip > 0:
            offset_statement = 'OFFSET %s'
            args.append(skip)
        

        _log.debug("About to do real_query")

        real_query = query.format(where=where_statement,
                                  limit=limit_statement,
                                  offset=offset_statement,
                                  order_by=order_by)
        _log.debug("Real Query: " + real_query)
        _log.debug("args: "+str(args))

        conn = self.connect()
        cur = conn.cursor()
        cur.execute(real_query, args)
        rows = cur.fetchall()
        if rows:
            values = [(ts.isoformat(), jsonapi.loads(value)) for ts, value in rows]
        else:
            values = {}
        cur.close()
        conn.close()
        return {'values':values}

    def execute(self, query, commit=True):
        conn = self.__connect()
        cur = conn.cursor()
        cur.execute(query)
        conn.commit()
        cur.close()
        conn.close()

    def connect(self):
        return self.__connect()

    def insert_data(self, ts, topic_id, data):
        conn = self.__connect()
        
        cur = conn.cursor()
        cur.execute('''REPLACE INTO data values(%s, %s, %s)''',
                                  (ts,topic_id,jsonapi.dumps(data)))
        conn.commit()
        cur.close()
        conn.close()
        
    def insert_topic(self, topic, commit=True):
        conn = self.__connect()
        
        cur = conn.cursor()
        cur.execute('''INSERT INTO topics (topic_name) values (%s)''', (topic,))
        row = [cur.lastrowid]
        conn.commit()
        cur.close()
        conn.close()

        return row

    def get_topic_map(self):        
        conn = self.__connect()
        cur = conn.cursor()
        cur.execute("SELECT * FROM topics")
        tm = {}

        while True:
            results = cur.fetchmany(1000)
            if not results:
                break
            for result in results:
                tm[result[1]] = result[0]

        cur.close()
        conn.close()
        return tm
