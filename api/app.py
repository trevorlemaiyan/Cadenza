from flask import Flask, redirect, request, session, url_for, render_template
import requests
from dotenv import load_dotenv
import os
from pymongo import MongoClient
from flask_socketio import SocketIO, send, join_room, leave_room
from urllib.parse import urlencode

load_dotenv()

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.secret_key = os.getenv("SECRET_KEY")
socketio = SocketIO(app, async_mode='eventlet')

client_id = os.getenv("SPOTIFY_CLIENT_ID")
client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
redirect_uri = os.getenv("REDIRECT_URI")

try:
    mongo_client = MongoClient(os.getenv("MONGO_URI"))
    db = mongo_client['cadenza_db']
    users_collection = db['users']
    # Ensure spotify_id is unique
    users_collection.create_index('spotify_id', unique=True)
    print("Connected to MongoDB")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login')
def login():
    scope = 'user-top-read user-read-private user-read-email'
    auth_url = 'https://accounts.spotify.com/authorize?' + urlencode({
        'response_type': 'code',
        'client_id': client_id,
        'scope': scope,
        'redirect_uri': redirect_uri,
    })
    return redirect(auth_url)


@app.route('/callback')
def callback():
    code = request.args.get('code')
    if not code:
        return redirect(url_for('index'))

    # Exchange code for access token
    try:
        token_response = requests.post(
            'https://accounts.spotify.com/api/token',
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': redirect_uri,
                'client_id': client_id,
                'client_secret': client_secret,
            }
        )
        token_data = token_response.json()
        access_token = token_data['access_token']
        session['access_token'] = access_token
    except Exception as e:
        print(f"Error fetching access token: {e}")
        return "Error fetching access token", 500

    # Fetch Spotify profile + top content
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        me = requests.get('https://api.spotify.com/v1/me', headers=headers).json()
        top_tracks = requests.get('https://api.spotify.com/v1/me/top/tracks', headers=headers).json()
        top_artists = requests.get('https://api.spotify.com/v1/me/top/artists', headers=headers).json()

        spotify_id = me['id']
        session['spotify_id'] = spotify_id

        avatar_url = me['images'][0]['url'] if me.get('images') else None

        users_collection.update_one(
            {'spotify_id': spotify_id},
            {'$set': {
                'spotify_id': spotify_id,
                'display_name': me.get('display_name') or spotify_id,
                'avatar_url': avatar_url,
                'access_token': access_token,
                'top_tracks': top_tracks,
                'top_artists': top_artists,
            }},
            upsert=True
        )
    except Exception as e:
        print(f"Error fetching Spotify data: {e}")
        return "Error fetching user data from Spotify", 500

    return redirect(url_for('profile'))


@app.route('/profile')
def profile():
    spotify_id = session.get('spotify_id')
    if not spotify_id:
        return redirect(url_for('login'))

    user = users_collection.find_one({'spotify_id': spotify_id})
    if not user:
        return redirect(url_for('login'))

    return render_template(
        'profile.html',
        display_name=user.get('display_name', spotify_id),
        avatar_url=user.get('avatar_url'),
        top_tracks=user.get('top_tracks', {}),
        top_artists=user.get('top_artists', {}),
    )


@app.route('/matches')
def get_matches():
    spotify_id = session.get('spotify_id')
    if not spotify_id:
        return redirect(url_for('login'))

    try:
        user = users_collection.find_one({'spotify_id': spotify_id})
        other_users = list(users_collection.find({'spotify_id': {'$ne': spotify_id}}))

        matches = []
        for other in other_users:
            similarity = calculate_similarity(user, other)
            room_id = '_'.join(sorted([spotify_id, other['spotify_id']]))
            matches.append({
                'display_name': other.get('display_name', other['spotify_id']),
                'avatar_url': other.get('avatar_url'),
                'similarity': round(similarity * 100),
                'room_id': room_id,
                'top_artist': other['top_artists']['items'][0]['name']
                    if other.get('top_artists', {}).get('items') else 'Unknown',
            })

        matches.sort(key=lambda x: x['similarity'], reverse=True)
    except Exception as e:
        print(f"Error fetching matches: {e}")
        return "Error fetching matches", 500

    return render_template('matches.html', matches=matches)


@app.route('/chat/<room_id>')
def chat(room_id):
    spotify_id = session.get('spotify_id')
    if not spotify_id:
        return redirect(url_for('login'))

    # Verify this user is part of this room
    user_ids = room_id.split('_')
    if spotify_id not in user_ids:
        return "Unauthorized", 403

    other_id = next((uid for uid in user_ids if uid != spotify_id), None)
    other_user = users_collection.find_one({'spotify_id': other_id}) if other_id else None
    other_name = other_user.get('display_name', other_id) if other_user else other_id

    return render_template('chat.html', room_id=room_id, other_name=other_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def calculate_similarity(user1, user2):
    try:
        ids1 = {a['id'] for a in user1['top_artists']['items']}
        ids2 = {a['id'] for a in user2['top_artists']['items']}
        union = ids1 | ids2
        if not union:
            return 0
        return len(ids1 & ids2) / len(union)
    except (KeyError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Socket.IO — private room-based chat
# ---------------------------------------------------------------------------

@socketio.on('join')
def on_join(data):
    room = data.get('room')
    if room:
        join_room(room)
        send('Connected to chat.', to=room)


@socketio.on('leave')
def on_leave(data):
    room = data.get('room')
    if room:
        leave_room(room)


@socketio.on('message')
def handle_message(data):
    room = data.get('room')
    msg = data.get('msg', '').strip()
    sender = data.get('sender', 'Someone')
    if room and msg:
        send({'msg': msg, 'sender': sender}, to=room)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run():
    socketio.run(app)


if __name__ == '__main__':
    socketio.run(app, debug=True)
