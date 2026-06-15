from run import app

with app.test_request_context():
    print('Registered routes:')
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        methods = ','.join(sorted(rule.methods))
        print(f'{rule.rule} -> {methods}')
