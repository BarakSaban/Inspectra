from flask import Flask, render_template

app = Flask(__name__, static_folder='static', template_folder='templates')

@app.route('/')
def index():
    return render_template('inspector_dashboard.html')

if __name__ == '__main__':
    app.run(debug=True)