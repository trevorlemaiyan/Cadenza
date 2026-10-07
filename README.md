# Cadenza - Music Match Chat App

Cadenza is a web-based application that connects users based on their Spotify music preferences. The app uses Spotify's Web API to fetch users' top tracks and artists, matches them with others who have similar tastes, and facilitates real-time chat between matched users. The goal is to create a social platform for music lovers to connect and discuss their favorite music.

## Features

- User authentication with Spotify
- Fetch and display user's top tracks and artists
- Match users based on music preferences
- Real-time chat between matched users

## Project Structure

cadenza/
├── api/
│ ├── init.py
│ └── app.py
├── templates/
│ ├── index.html
│ ├── profile.html
│ ├── matches.html
│ ├── chat.html
├── static/
│ └── app.js
├── .env
├── requirements.txt
├── vercel.json
└── README.md


## Installation

1. Clone the repository:

    ```bash
    git clone https://github.com/your-username/cadenza.git
    cd cadenza
    ```

2. Create and activate a virtual environment:

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. Install the dependencies:

    ```bash
    pip install -r requirements.txt
    ```

4. Create a `.env` file in the root directory with your Spotify and MongoDB credentials:

    ```
    SPOTIFY_CLIENT_ID=your_spotify_client_id
    SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
    REDIRECT_URI=http://localhost:5000/callback
    SECRET_KEY=your_secret_key
    MONGO_URI=your_mongodb_uri
    ```

5. Run the application:

    ```bash
    gunicorn -w 4 -k geventwebsocket.gunicorn.workers.GeventWebSocketWorker wsgi:app
    ```

6. Open a web browser and navigate to `http://localhost:8000`.

## Deployment

To deploy the application on Vercel:

1. Install Vercel CLI:

    ```bash
    npm install -g vercel
    ```

2. Login to Vercel:

    ```bash
    vercel login
    ```

3. Deploy the application:

    ```bash
    vercel
    ```

4. Add the environment variables to your Vercel project settings.

5. Access your deployed application through the provided Vercel URL.

## License

This project is licensed under the MIT License.
