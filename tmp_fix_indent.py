import sys

filepath = 'database/manager.py'

with open(filepath, 'rb') as f:
    content = f.read()

# Replace the incorrectly indented PRAGMA foreign_keys = OFF line
# 16 spaces -> 8 spaces
old = b'                conn.execute("PRAGMA foreign_keys = OFF")'
new = b'        conn.execute("PRAGMA foreign_keys = OFF")'
content = content.replace(old, new, 1)

# Replace the incorrectly indented PRAGMA foreign_keys = ON line
old2 = b'                conn.execute("PRAGMA foreign_keys = ON")\n            logger.info("Migration FK_ON_DELETE_RESTRICT conclu'
new2 = b'            conn.execute("PRAGMA foreign_keys = ON")\n            logger.info("Migration FK_ON_DELETE_RESTRICT conclu'
content = content.replace(old2, new2, 1)

with open(filepath, 'wb') as f:
    f.write(content)

print('OK')