"""Create the first local administrator in an EMPTY installation only."""
import getpass
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stometric.web  # router registration order
from stometric import auth, db


def create(c, email, password, workspace):
    if '@' not in email or len(password) < 12 or not workspace.strip():
        raise ValueError('Email, workspace and a password of at least 12 characters are required')
    # Serializes two first-install attempts, refuses any existing user data.
    c.execute('SELECT pg_advisory_xact_lock(11876432)')
    if c.execute('SELECT 1 FROM users LIMIT 1').fetchone() or c.execute('SELECT 1 FROM workspaces LIMIT 1').fetchone():
        raise ValueError('Installation is not empty; use account administration instead')
    ws = c.execute("INSERT INTO workspaces(name,plan) VALUES (%s,'mcp') RETURNING id", (workspace.strip(),)).fetchone()['id']
    uid = c.execute('INSERT INTO users(email,name,password_hash,is_superadmin) VALUES (%s,%s,%s,true) RETURNING id',
                    (email.strip().lower(), 'Administrator', auth.hash_password(password))).fetchone()['id']
    c.execute("INSERT INTO memberships(user_id,workspace_id,role) VALUES (%s,%s,'owner')", (uid, ws))
    c.execute("INSERT INTO audit_log(user_id,workspace_id,action) VALUES (%s,%s,'installation/bootstrap')", (uid, ws))
    return uid, ws


if __name__ == '__main__':
    db.migrate()
    email = input('Administrator email: ')
    workspace = input('Workspace name: ')
    password = getpass.getpass('New password (12+ characters): ')
    if password != getpass.getpass('Repeat password: '):
        raise SystemExit('Passwords differ')
    with db.connect() as c:
        create(c, email, password, workspace)
    print('Administrator created. Sign in over HTTPS.')
