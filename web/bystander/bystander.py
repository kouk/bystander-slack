import json
import random
import re
from uuid import uuid4

from redis import Redis

from .conf import EXPIRE_SECONDS, REDIS_HOST
from .slack import (get_members, get_usergroup, post_channel, post_ephemeral,
                    user_is_active)


REDIS = Redis(REDIS_HOST, '6379')


class BystanderError(Exception):
    pass


class Bystander(object):
    """ Class to do the heavylifting of the app.

        All the methods (so far) are public and define the interface of the
        class. It is advised to not call any of these methods from within the
        class.
    """

    def __init__(self, raw_text, requester_id, channel_id):
        self.id = None
        self.user_id = None
        self.raw_text = raw_text
        self.requester_id = requester_id
        self.channel_id = channel_id
        self.rejected_user_ids = []

    @classmethod
    def load(cls, id):
        data = REDIS.get(id)

        if data is None:
            raise BystanderError("Request has likely expired")

        data = json.loads(data)

        bystander = cls(data['text'], data['requester_id'], data['channel_id'])
        bystander.id = id
        bystander.user_id = data['user_id']
        bystander.user_ids = data['user_ids']
        bystander.usergroup_ids = data['usergroup_ids']
        bystander.text = data['text']
        bystander.rejected_user_ids = data['rejected_user_ids']

        return bystander

    def start(self):
        random.shuffle(self.user_ids)
        self.user_id = self.user_ids[0]
        self.id = str(uuid4())

    def save(self):
        assert self.user_id
        REDIS.set(self.id,
                  json.dumps({'user_ids': self.user_ids,
                              'user_id': self.user_id,
                              'usergroup_ids': self.usergroup_ids,
                              'text': self.text,
                              'requester_id': self.requester_id,
                              'channel_id': self.channel_id,
                              'rejected_user_ids': self.rejected_user_ids}),
                  ex=EXPIRE_SECONDS)

    def delete(self):
        REDIS.delete(self.id)

    def process_text(self):
        """ Process the raw text of the request into the users and groups it's
            directed at
        """

        users_pat = re.compile(r'<@([^|]+)\|[^>]+>')
        usergroups_pat = re.compile(r'<!subteam\^([^|]+)\|@[^>]+>')

        # Find users
        self.user_ids = [match.groups()[0]
                         for match in users_pat.finditer(self.raw_text)]
        self.usergroup_ids = [
            match.groups()[0]
            for match in usergroups_pat.finditer(self.raw_text)
        ]

        # Clean text
        self.text = users_pat.sub('', self.raw_text)
        self.text = usergroups_pat.sub('', self.text)
        self.text = re.sub(r'\s+', ' ', self.text).strip()

    def resolve_usergroups(self):
        "Expand the usergroups into their lists of users"

        user_ids = set(self.user_ids)
        for i, usergroup_id in enumerate(self.usergroup_ids):
            user_ids |= set(get_usergroup(usergroup_id))
        self.user_ids = list(user_ids)

    def filter_out_inactive_users(self):
        self.user_ids = [user_id
                         for user_id in self.user_ids
                         if user_is_active(user_id)]

    def filter_out_users_not_in_channel(self):
        "Filter out members that don't belong to the channel"

        self.user_ids = list(set(self.user_ids) &
                             set(get_members(self.channel_id)))

    def filter_out_requester(self):
        try:
            self.user_ids.remove(self.requester_id)
        except ValueError:
            pass

    @property
    def user_ids_left(self):
        return list(set(self.user_ids) - set(self.rejected_user_ids))

    def send_buttons(self):
        """ Send the message with the buttons to a randomly selected user in
            the request
        """
        if self.user_id is None:
            raise Exception("No user ID assigned. Forget to call .save()?")
        post_ephemeral(self.channel_id, self.user_id,
                       "<@{}>, <@{}> has asked you to:".
                       format(self.user_id, self.requester_id),
                       [{'text': self.text},
                        {'text': "Are you up for it:?",
                         "callback_id": "{}".format(self.id),
                         "attachment_type": "default",
                         "actions": [{'name': "yes", 'text': "Accept",
                                      'type': "button", 'value': "yes",
                                      'style': "primary"},
                                     {'name': "no", 'text': "Reject",
                                      'type': "button", 'value': "no",
                                      'style': "danger"}]}])

    def _next_user(self, skip_user):
        """Return the next user after skipping the given user.

        By default returns the first user ID not in the rejected users list
        after skipping those user ids that precede the skip_user.

        Returns None if no user could be found (for whatever reason).
        """
        remaining = self.user_ids
        if skip_user in remaining:
            idx = remaining.index(skip_user)
            remaining = remaining[idx + 1:]
        for uid in remaining:
            if uid in self.rejected_user_ids:
                continue
            return uid
        return None

    def reject(self, user_id):
        self.rejected_user_ids.append(user_id)

    def skip(self, user_id):
        self.user_id = self._next_user(user_id)

    def accept(self, user_id):
        post_channel(self.channel_id,
                     "<@{}> accepted <@{}>'s request to:".
                     format(user_id, self.requester_id),
                     [{'text': self.text}])

    def abort(self):
        post_ephemeral(self.channel_id, self.requester_id,
                       ("I'm sorry. It appears that everyone rejected your "
                        "request :cry:"),
                       [{'text': self.text}])

    def giveup(self):
        post_ephemeral(self.channel_id, self.requester_id,
                       ("<@{}>, {} people were notified but no one has "
                        "accepted yet. We give up! :rage:").format(
                            self.requester_id, len(self.user_ids)))
