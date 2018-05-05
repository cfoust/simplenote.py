# -*- coding: utf-8 -*-
"""
    simplenote.py
    ~~~~~~~~~~~~~~

    Python library for accessing the Simplenote API

    :copyright: (c) 2011 by Daniel Schauenberg
    :copyright: (c) 2018 by Caleb Foust
    :license: MIT, see LICENSE for more details.
"""

import base64
import datetime
import json
import requests
import sys
import time

AUTH_URL = 'https://app.simplenote.com/api/login'
DATA_URL = 'https://app.simplenote.com/api2/data'
INDX_URL = 'https://app.simplenote.com/api2/index?'
NOTE_FETCH_LENGTH = 100

class SimplenoteLoginFailed(Exception):
    pass

class Simplenote(object):
    """ Class for interacting with the simplenote web service """

    def __init__(self, username, password):
        """ object constructor """
        self.username = username
        self.password = password
        self.token = None
        self.mark = "mark"
        self.session = requests.Session()

    def authenticate(self, user, password):
        """ Method to get simplenote auth token

        Arguments:
            - user (string):     simplenote email address
            - password (string): simplenote password

        Returns:
            Simplenote API token as string

        """
        auth_params = "email={0}&password={1}".format(user, password)

        try:
            values = base64.b64encode(bytes(auth_params,'utf-8'))
        except TypeError:
            values = base64.encodestring(auth_params)

        response = self.session.post(AUTH_URL, data=values)

        try:
            res = response.text
            token = res
        except HTTPError:
            raise SimplenoteLoginFailed('Login to Simplenote API failed!')
        except IOError: # no connection exception
            token = None
        return token

    def get_token(self):
        """ Method to retrieve an auth token.

        The cached global token is looked up and returned if it exists. If it
        is `None` a new one is requested and returned.

        Returns:
            Simplenote API token as string

        """
        if self.token == None:
            self.token = self.authenticate(self.username, self.password)
        try:
            return str(self.token,'utf-8')
        except TypeError:
            return self.token

    def get_auth_params(self):
        return {
                'auth' : self.get_token(),
                'email' : self.username
                }

    def get_note(self, noteid, version=None):
        """ method to get a specific note

        Arguments:
            - noteid (string): ID of the note to get
            - version (int): optional version of the note to get

        Returns:
            A tuple `(note, status)`

            - note (dict): note object
            - status (int): 0 on sucesss and -1 otherwise

        """
        # request note
        params_version = ""
        if version is not None:
            params_version = '/' + str(version)
         
        url = "%s/%s%s" % (DATA_URL, noteid, params_version)

        try:
            response = self.session.get(url, params=self.get_auth_params())
        except HTTPError as e:
            return e, -1
        except IOError as e:
            return e, -1

        note = response.json()
        note = self.__encode(note)

        return note, 0

    def update_note(self, note):
        """ function to update a specific note object, if the note object does not
        have a "key" field, a new note is created

        Arguments
            - note (dict): note object to update

        Returns:
            A tuple `(note, status)`

            - note (dict): note object
            - status (int): 0 on sucesss and -1 otherwise

        """

        note = self.__decode(note)
        # determine whether to create a new note or update an existing one
        if "key" in note:
            # set modification timestamp if not set by client
            if 'modifydate' not in note:
                note["modifydate"] = time.time()

            url = '{0}/{1}'.format(DATA_URL, note["key"])
        else:
            url = DATA_URL

        try:
            response = self.session.post(url, params=self.get_auth_params(), json=note)
        except IOError as e:
            return e, -1

        note = response.json()
        note = self.__encode(note)

        return note, 0

    def add_note(self, note):
        """wrapper function to add a note

        The function can be passed the note as a dict with the `content`
        property set, which is then directly send to the web service for
        creation. Alternatively, only the body as string can also be passed. In
        this case the parameter is used as `content` for the new note.

        Arguments:
            - note (dict or string): the note to add

        Returns:
            A tuple `(note, status)`

            - note (dict): the newly created note
            - status (int): 0 on sucesss and -1 otherwise

        """

        if type(note) == str:
            return self.update_note({"content": note})
        elif (type(note) == dict) and "content" in note:
            return self.update_note(note)
        else:
            return "No string or valid note.", -1

    def get_note_list(self, since=None, tags=[]):
        """ function to get the note list

        The function can be passed optional arguments to limit the
        date range of the list returned and/or limit the list to notes
        containing a certain tag. If omitted a list of all notes
        is returned.

        Arguments:
            - since=YYYY-MM-DD string: only return notes modified
              since this date
            - tags=[] list of tags as string: return notes that have
              at least one of these tags

        Returns:
            A tuple `(notes, status)`

            - notes (list): A list of note objects with all properties set except
            `content`.
            - status (int): 0 on sucesss and -1 otherwise

        """
        # initialize data
        status = 0
        ret = []
        notes = { "data" : [] }
        self.mark = "mark"

        params = self.get_auth_params()
        params['length'] = NOTE_FETCH_LENGTH

        try:
            sinceUT = time.mktime(datetime.datetime.strptime(since, "%Y-%m-%d").timetuple())
            params['since'] = sinceUT
        except (TypeError, ValueError):
            #I.e. None or invalid date format
            pass

        # get notes
        while self.mark:
            notes, status = self.__get_notes(notes, params)

        # parse data fields in response
        note_list = notes["data"]

        # Can only filter for tags at end, once all notes have been retrieved.
        #Below based on simplenote.vim, except we return deleted notes as well
        if (len(tags) > 0):
            note_list = [n for n in note_list if (len(set(n["tags"]).intersection(tags)) > 0)]

        return note_list, status

    def trash_note(self, note_id):
        """ method to move a note to the trash

        Arguments:
            - note_id (string): key of the note to trash

        Returns:
            A tuple `(note, status)`

            - note (dict): the newly created note or an error message
            - status (int): 0 on sucesss and -1 otherwise

        """
        # get note
        note, status = self.get_note(note_id)

        if (status == -1):
            return note, status

        # set deleted property
        note["deleted"] = 1

        # update note
        return self.update_note(note)

    def delete_note(self, note_id):
        """ method to permanently delete a note

        Arguments:
            - note_id (string): key of the note to trash

        Returns:
            A tuple `(note, status)`

            - note (dict): an empty dict or an error message
            - status (int): 0 on sucesss and -1 otherwise

        """
        # notes have to be trashed before deletion
        note, status = self.trash_note(note_id)

        if (status == -1):
            return note, status

        url = "%s/%s" % (DATA_URL, str(note_id))

        try:
            self.session.delete(DATA_URL, params=self.get_auth_params())
        except IOError as e:
            return e, -1

        return {}, 0

    def __get_notes(self, notes, params):
        """ Private method to fetch a chunk of notes

        Arguments:
            - Notes
            - URL parameters
            - since date

        Returns:
            - Notes
            - Status

        """

        notes_index = {}

        if self.mark != "mark":
            params['mark'] = self.mark

        try:
            response = self.session.get(INDX_URL, params=params)
            notes_index = response.json()
            notes["data"].extend(notes_index["data"])
            status = 0
        except IOError:
            status = -1

        if "mark" in notes_index:
            self.mark = notes_index["mark"]
        else:
            self.mark = ""

        return notes, status

    def __encode(self, note):
        """ Private method to UTF-8 encode for Python 2

        Arguments:
            A note

        Returns:
            A note

        """

        if sys.version_info < (3, 0):
            if "content" in note:
                # use UTF-8 encoding
                note["content"] = note["content"].encode('utf-8')
                # For early versions of notes, tags not always available
            if "tags" in note:
                note["tags"] = [t.encode('utf-8') for t in note["tags"]]
        return note

    def __decode(self, note):
        """ Utility method to UTF-8 decode for Python 2

        Arguments:
            A note

        Returns:
            A note

        """
        if sys.version_info < (3, 0):
            if "content" in note:
                note["content"] = unicode(note["content"], 'utf-8')
            if "tags" in note:
                note["tags"] = [unicode(t, 'utf-8') for t in note["tags"]]
        return note
