import sys
sys.path.insert(0, 'c:/Users/User/Documents/INSPECTRA/Git/Inspectra')
from run import app

print('root', sys.path[0])
print('Routes:')
for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    print(rule.rule, sorted(rule.methods))
