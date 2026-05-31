import re

path = r'c:\docker\gisnas\gisnas_sketsa\sketsa_dialogs.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('"Refresh will overwrite local data with server data.\n"', '"Refresh will overwrite local data with server data.\\n"')
content = content.replace('"Unpushed local changes will be lost.\n\n"', '"Unpushed local changes will be lost.\\n\\n"')
content = content.replace('"Changes to be sent to server:\n"', '"Changes to be sent to server:\\n"')
content = content.replace(' to GISNAS server?\nThis will create a new collection and upload all features."', ' to GISNAS server?\\nThis will create a new collection and upload all features."')
content = content.replace(' successfully uploaded!\n\nCollection Name: ', ' successfully uploaded!\\n\\nCollection Name: ')
content = content.replace('Failed to upload layer:\n', 'Failed to upload layer:\\n')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
