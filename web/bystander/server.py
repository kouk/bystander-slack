import json
from flask import Flask, request, jsonify, abort

from .conf import INCOMING_TOKEN
from .tasks import start_bystander, accept_bystander, reject_bystander


app = Flask(__name__)


@app.route('/command', methods=['POST'])
def command():
    if request.form.get('token', None) != INCOMING_TOKEN:
        abort(401)

    try:
        raw_text = request.form['text']
        user_id = request.form['user_id']
        channel_id = request.form['channel_id']
    except KeyError:
        return jsonify({'response_type': "ephemeral",
                        'text': ("I'm sorry, your request appears to be "
                                 "malformed, please try again")})

    app.logger.info("Got request with raw_text: '%s', user_id: '%s', "
                    "channel_id: '%s'",
                    raw_text, user_id, channel_id)
    start_bystander.delay(raw_text, user_id, channel_id)
    return jsonify({'response_type': "ephemeral",
                    'text': "Roger, will assign the task to a teammate",
                    'attachments': [{'text': raw_text}]})


@app.route('/button', methods=['POST'])
def button():
    # Maybe key errors and stuff here, look out
    data = json.loads(request.form['payload'])

    if data['token'] != INCOMING_TOKEN:
        abort(401)

    id = data['callback_id']
    user_id = data['user']['id']
    channel_id = data['channel']['id']

    if data['actions'][0]['name'] == "yes":
        accept_bystander.delay(id, user_id, channel_id)
    else:
        reject_bystander.delay(id, user_id, channel_id)

    return jsonify({'response_type': "ephemeral",
                    'text': "Thank you for your choice"})
