# By: Dwait
# Level: 4
# TrueTrader is a stock market simulator to help kids learn about stocks and the market.

# Import libraries (these are like toolkits with useful functions)
import os
import logging
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, Response
from pymongo import MongoClient  # To connect to our database
import yfinance as yf  # To get real stock data from the internet
import datetime as dt
from dotenv import load_dotenv  # Loads hidden secret keys safely
from passlib.hash import sha256_crypt

# Create the Flask app (like starting our website)
app = Flask(__name__)
app.secret_key = os.getenv('SHA256_SALT')
# Load secret keys from the .env file (keeps things safe)
load_dotenv()

# Connect to MongoDB database using a secure link
uri = os.getenv("MONGO_URI")
client = MongoClient(uri, tls=True, tlsAllowInvalidCertificates=True)
db = client["users_collection"]
users_collection = db["users"]  # Stores usernames and passwords
portfolio_collection = db["portfolios"]  # Stores each user's stock portfolio

# Secret key for login sessions (helps keep track of who's logged in)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'supersecretkey')
app.config['SESSION_TYPE'] = 'filesystem'

# Set up logging to see what's happening in our app
logging.basicConfig(level=logging.INFO)

# Function to get the current price of a stock
def get_stock_price(symbol):
    try:
        stock = yf.Ticker(symbol)
        data = stock.history(period="1d")  # Get today’s data
        if not data.empty:
            return round(data['Close'][-1], 2)  # Return last closing price
        logging.warning(f"No data returned for {symbol}")
        return None
    except Exception as e:
        logging.error(f"Error fetching price for {symbol}: {str(e)}")
        return None

# Function to get stock price chart data for graphing
def get_bar_data(symbol, timeframe):
    try:
        # Set how many days of data we want based on timeframe
        if timeframe in ('1m', '5m', '30m'):
            days = 7 if timeframe == '1m' else 60
            start_date = dt.datetime.now() - dt.timedelta(days=days)
        else:
            start_date = None

        data = yf.download(symbol, start=start_date, interval=timeframe)
        if data.empty:
            logging.warning(f"No bar data returned for {symbol} with {timeframe} timeframe.")
            return False
        return data
    except Exception as e:
        logging.error(f"Error fetching bar data for {symbol}: {str(e)}")
        return False

# Redirect the home page to the dashboard
@app.route('/')
def index():
    return redirect(url_for('dashboard'))

# Register new users
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = sha256_crypt.hash(request.form['password'])

        # Check if user already exists
        if users_collection.find_one({'username': username}):
            flash('Username already exists. Choose a different one.', 'danger')
        else:
            users_collection.insert_one({'username': username, 'password': password})
            flash('Registration successful. You can now log in.', 'success')
            return redirect(url_for('login'))

    return render_template('register.html')

# Login existing users
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Check login credentials
        user = users_collection.find_one({'username': username})
        if user and sha256_crypt.verify(password, user['password']):
            session['username'] = username
            flash('Login successful.', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password. Please try again.', 'danger')

    return render_template('login.html')

# Logout the user
@app.route('/logout')
def logout():
    session.pop('username', None)
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))

# Dashboard where users manage stocks
@app.route('/dashboard', methods=['GET', 'POST'])
def dashboard():
    # Check if user is logged in
    if 'username' not in session:
        return redirect(url_for('login'))

    # Get user data and their portfolio
    user = users_collection.find_one({'username': session['username']})
    portfolio = portfolio_collection.find_one({'user_id': user['_id']})

    # If no portfolio, give them $10,000 to start
    if not portfolio:
        portfolio = {'user_id': user['_id'], 'stocks': {}, 'cash': 10000}
        portfolio_collection.insert_one(portfolio)

    # Show user how much their portfolio is worth
    portfolio_value = 0
    stock_info = {}

    for symbol, data in portfolio['stocks'].items():
        quantity = data['quantity']
        buy_price = data['buy_price']
        current_price = get_stock_price(symbol)

        if current_price:
            stock_info[symbol] = {
                'quantity': quantity,
                'buy_price': buy_price,
                'current_price': current_price
            }
            portfolio_value += quantity * current_price

    # Handle buying or selling a stock
    if request.method == 'POST':
        symbol = request.form['symbol'].upper()
        action = request.form['action']
        quantity = int(request.form['quantity'])
        price = get_stock_price(symbol)

        if not price:
            flash("Invalid stock symbol.", "danger")
            return redirect(url_for('dashboard'))

        portfolio = portfolio_collection.find_one({'user_id': user['_id']})
        stocks = portfolio.get('stocks', {})
        cash = portfolio.get('cash', 10000)
        cost = quantity * price

        if action == 'buy':
            if cost > cash:
                flash("Not enough cash to complete this purchase.", "danger")
            else:
                if symbol in stocks:
                    existing = stocks[symbol]
                    total_quantity = existing['quantity'] + quantity
                    avg_price = ((existing['quantity'] * existing['buy_price']) + (quantity * price)) / total_quantity
                    stocks[symbol] = {'quantity': total_quantity, 'buy_price': avg_price}
                else:
                    stocks[symbol] = {'quantity': quantity, 'buy_price': price}
                cash -= cost
                flash(f'Bought {quantity} shares of {symbol}', 'success')

        elif action == 'sell':
            if symbol not in stocks or stocks[symbol]['quantity'] < quantity:
                flash("Not enough shares to sell.", "danger")
            else:
                stocks[symbol]['quantity'] -= quantity
                if stocks[symbol]['quantity'] == 0:
                    del stocks[symbol]
                cash += cost
                flash(f'Sold {quantity} shares of {symbol}', 'success')

        # Save changes back to the database
        portfolio_collection.update_one(
            {'user_id': user['_id']},
            {'$set': {'stocks': stocks, 'cash': cash}}
        )
        return redirect(url_for('dashboard'))

    return render_template(
        'dashboard.html',
        portfolio=portfolio,
        stock_info=stock_info,
        portfolio_value=round(portfolio_value, 2)
    )

# API endpoint to get stock price (used by frontend JavaScript)
@app.route('/api/stock_price/', methods=['GET'])
def api_stock_price():
    symbol = request.args.get('symbol')
    if not symbol:
        return jsonify({"error": "No symbol provided"}), 400

    price = get_stock_price(symbol.upper())
    if price:
        return jsonify({symbol.upper(): price}), 200
    return jsonify({"error": "Invalid symbol"}), 404

# Renders an interactive chart in the browser
@app.route('/chart/<symbol>')
def chart(symbol):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{symbol} Chart</title>
        <script src="https://code.highcharts.com/highcharts.js"></script>
        <script src="https://code.highcharts.com/modules/stock.js"></script>
        <style>
            html, body {{
                margin: 0;
                padding: 0;
                height: 100%;
            }}
            #chart {{
                height: 100%;
            }}
        </style>
    </head>
    <body>
        <div id="chart"></div>
        <script>
            Highcharts.stockChart('chart', {{
                rangeSelector: {{
                    selected: 1
                }},
                title: {{
                    text: '{symbol} Stock Chart'
                }},
                series: [{{
                    type: 'candlestick',
                    name: '{symbol}',
                    data: []
                }}]
            }});

            fetch('/api/chart_data/{symbol}')
                .then(response => response.json())
                .then(data => {{
                    const chart = Highcharts.charts[0];
                    chart.series[0].setData(data);
                }});
        </script>
    </body>
    </html>
    """
    return Response(html, mimetype='text/html')

# Returns chart data (price history) as JSON
@app.route('/api/chart_data/<symbol>')
def chart_data(symbol):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="20y", interval="1d", auto_adjust=True)

        if data.empty:
            return jsonify({"error": "No data found for the symbol"}), 404

        chart_data = []
        for timestamp, row in data.iterrows():
            chart_data.append([
                int(timestamp.timestamp() * 1000),  # Date in milliseconds
                float(row['Open']),
                float(row['High']),
                float(row['Low']),
                float(row['Close'])
            ])
        return jsonify(chart_data)

    except Exception as e:
        return jsonify({"error": f"Failed to fetch chart data: {str(e)}"}), 500

# Endpoint to get detailed daily stock history for a year
@app.route("/api/stock_history/<symbol>")
def stock_history(symbol):
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1y", interval="1d", auto_adjust=True)

        if hist.empty:
            return jsonify([])

        data = []
        for index, row in hist.iterrows():
            data.append({
                "date": index.strftime("%Y-%m-%d"),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
                "volume": int(row["Volume"]),
            })

        return jsonify(data)

    except Exception as e:
        print(f"Error fetching stock history for {symbol}: {e}")
        return jsonify({"error": "internal error"}), 500

# Start the Flask app
if __name__ == "__main__":
    app.run(debug=False, port=5000)
