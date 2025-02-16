import os

directory = "/Users/dmi.fefelov/Downloads"
for root, dirs, files in os.walk(directory):
    for file in files:
        if file.endswith(".tsv.gz"):
            print(os.path.join(root, file))