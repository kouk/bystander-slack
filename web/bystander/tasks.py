from celery.utils.log import get_task_logger

from .bystander import Bystander, BystanderError
from .conf import TIMEOUT_SECONDS
from .celery import app
from .slack import post_ephemeral, SlackError


logger = get_task_logger(__name__)


def notify_expired(user_id, channel_id):
    post_ephemeral(channel_id, user_id,
                   ("It looks like this request has timed out before "
                    "you could accept it, or someone else already "
                    "accepted it."))


@app.task(name='bystander_start')
def start_bystander(raw_text, requester_id, channel_id):
    bystander = Bystander(raw_text, requester_id, channel_id)
    bystander.process_text()
    logger.info("After processing text: raw_text: '%s', user_ids: '%s', "
                "usergroup_ids: '%s', text: '%s'",
                raw_text, bystander.user_ids, bystander.usergroup_ids,
                bystander.text)
    try:
        bystander.resolve_usergroups()
        bystander.filter_out_users_not_in_channel()
        bystander.filter_out_requester()
        bystander.filter_out_inactive_users()
    except SlackError as e:
        post_ephemeral(channel_id, requester_id,
                       ("Something went wrong while trying to contact the "
                        "Slack API, please try again later. Error was:"),
                       [{'text': str(e)}])
        return

    if len(bystander.user_ids) < 2:
        post_ephemeral(channel_id, requester_id,
                       "You need to specify at least 2 active users in your "
                       "request")
        return

    bystander.start()
    bystander.save()
    bystander.send_buttons()
    skip_bystander.apply_async((bystander.id, bystander.user_id),
                               countdown=TIMEOUT_SECONDS)


@app.task(name='bystander_accept')
def accept_bystander(id, user_id, channel_id):
    try:
        bystander = Bystander.load(id)
    except BystanderError:
        notify_expired(user_id, channel_id)
    else:
        bystander.accept(user_id)
        bystander.delete()


@app.task(name='bystander_reject')
def reject_bystander(id, user_id, channel_id):
    try:
        bystander = Bystander.load(id)
    except BystanderError:
        notify_expired(user_id, channel_id)
        return
    bystander.reject(user_id)

    if bystander.user_id != user_id:
        return
    bystander.skip(user_id)

    if bystander.user_id:
        bystander.save()
        bystander.send_buttons()
        skip_bystander.apply_async((bystander.id, bystander.user_id),
                                   countdown=TIMEOUT_SECONDS)
    else:
        bystander.abort()
        bystander.delete()


@app.task(name='bystander_skip')
def skip_bystander(id, user_id):
    try:
        bystander = Bystander.load(id)
    except BystanderError:
        return

    if bystander.user_id != user_id:
        return
    bystander.skip(user_id)

    if bystander.user_id:
        bystander.save()
        bystander.send_buttons()
        skip_bystander.apply_async((bystander.id, bystander.user_id),
                                   countdown=TIMEOUT_SECONDS)
    else:
        bystander.giveup()
