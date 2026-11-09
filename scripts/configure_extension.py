"""Configure an unpacked extension. ZIP downloaded from the site is configured automatically."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stometric.extension_package import configured_files, ExtensionConfigError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origin',help='Your real HTTPS site origin')
    args=parser.parse_args()
    directory=Path(__file__).resolve().parents[1]/'extension'
    try:files=configured_files(directory,args.origin)
    except ExtensionConfigError as error:parser.error(str(error))
    # Validate every file and origin before any change. Credentials are not used.
    for name,content in files.items():
        if name in ('manifest.json','bg.js','popup.html','wb.js'):(directory/name).write_bytes(content)
    print('Extension configured for this installation. Reload it in Chrome and reload WB tabs.')


if __name__=='__main__':main()
