# main.py

import requests
import argparse
import os
import json
import subprocess
import zipfile
import shutil
from datetime import datetime
from io import BytesIO
from tqdm import tqdm
from dbutils import (
    connect_to_db,
    delete_results_table,
    insert_result_into_db,
    insert_plugin_into_db,
    insert_theme_into_db,
)
import sys

# Constants
PLUGIN_API_URL = 'https://api.wordpress.org/plugins/info/1.2/'
THEME_API_URL = 'https://api.wordpress.org/themes/info/1.2/'

def get_plugins(page=1, per_page=100):
    params = {
        'action': 'query_plugins',
        'request[page]': page,
        'request[per_page]': per_page,
        'request[fields][active_installs]': True,
        'request[fields][download_link]': True,
        'request[fields][modified]': True,
        'request[fields][added]': True,
        'request[fields][slug]': True,
        'request[fields][version]': True,
        'request[fields][downloaded]': True,
        'request[fields][author]': True,
        'request[browse]': 'popular'
    }
    response = requests.get(PLUGIN_API_URL, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to retrieve plugins: {response.status_code}")
        return None

def get_themes(page=1, per_page=100):
    params = {
        'action': 'query_themes',
        'request[page]': page,
        'request[per_page]': per_page,
        'request[fields][active_installs]': True,
        'request[fields][download_link]': True,
        'request[fields][last_updated]': True,
        'request[fields][added]': True,
        'request[fields][slug]': True,
        'request[fields][version]': True,
        'request[fields][downloaded]': True,
        'request[fields][author]:': True,
        'request[browse]': 'popular'
    }
    response = requests.get(THEME_API_URL, params=params)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Failed to retrieve themes: {response.status_code}")
        return None

def write_plugins_to_db_and_download(db_conn, cursor, download_dir, verbose=False):
    # Get the first page to find out the total number of pages
    data = get_plugins(page=1)

    if not data or "info" not in data:
        print("Failed to retrieve the plugin information.")
        return

    total_pages = data["info"]["pages"]

    # Ensure the directory for plugins exists
    os.makedirs(os.path.join(download_dir, "plugins"), exist_ok=True)

    # Iterate through the pages
    for page in tqdm(range(1, total_pages + 1), desc="Processing plugins"):
        data = get_plugins(page=page)

        if not data or "plugins" not in data:
            break

        for plugin in data["plugins"]:
            active_installs = plugin.get('active_installs', 0)
            if active_installs >= 1000:
                # Insert plugin into database
                insert_plugin_into_db(cursor, plugin)
                db_conn.commit()

                if verbose:
                    print(f"Inserted data for plugin {plugin['slug']}.")

                # Download and extract the plugin
                download_and_extract_item(plugin, 'plugin', download_dir, verbose)

def write_themes_to_db_and_download(db_conn, cursor, download_dir, verbose=False):
    # Get the first page to find out the total number of pages
    data = get_themes(page=1)

    if not data or "info" not in data:
        print("Failed to retrieve the theme information.")
        return

    total_pages = data["info"]["pages"]

    # Ensure the directory for themes exists
    os.makedirs(os.path.join(download_dir, "themes"), exist_ok=True)

    # Iterate through the pages
    for page in tqdm(range(1, total_pages + 1), desc="Processing themes"):
        data = get_themes(page=page)

        if not data or "themes" not in data:
            break

        for theme in data["themes"]:
            active_installs = theme.get('active_installs', 0)
            if active_installs >= 1000:
                # Insert theme into database
                insert_theme_into_db(cursor, theme)
                db_conn.commit()

                if verbose:
                    print(f"Inserted data for theme {theme['slug']}.")

                # Download and extract the theme
                download_and_extract_item(theme, 'theme', download_dir, verbose)

def download_and_extract_item(item, item_type, download_dir, verbose):
    slug = item["slug"]

    # For plugins, use 'modified' date
    if item_type == 'plugin':
        last_updated = item.get("modified")
    else:
        last_updated = item.get("last_updated")

    # Parse the date
    last_updated_datetime = parse_date(last_updated)

    if item_type == 'theme':
        # Skip themes not updated in the last 2 years
        if not last_updated_datetime or last_updated_datetime.year < (datetime.now().year - 2):
            return
    else:
        # For plugins, proceed even if last_updated_datetime is None
        pass

    # Construct the download link
    download_link = item.get("download_link")
    if not download_link or download_link == '':
        if item_type == 'plugin':
            download_link = f"https://downloads.wordpress.org/plugin/{slug}.latest-stable.zip"
        elif item_type == 'theme':
            download_link = f"https://downloads.wordpress.org/theme/{slug}.zip"

    # Proceed to download and extract
    item_path = os.path.join(download_dir, f"{item_type}s", slug)

    # Clear the directory if it exists
    if os.path.exists(item_path):
        if verbose:
            print(f"{item_type.capitalize()} folder already exists, deleting folder: {item_path}")
        shutil.rmtree(item_path)

    try:
        if verbose:
            print(f"Downloading and extracting {item_type}: {slug}")
        response = requests.get(download_link)
        response.raise_for_status()
        with zipfile.ZipFile(BytesIO(response.content)) as z:
            z.extractall(item_path)
    except requests.RequestException as e:
        print(f"Failed to download {slug}: {e}")
    except zipfile.BadZipFile:
        print(f"Failed to unzip {slug}: Not a zip file or corrupt zip file")

def run_semgrep_and_store_results(db_conn, cursor, download_dir, config, verbose=False):
    items = [('plugin', os.path.join(download_dir, "plugins")), ('theme', os.path.join(download_dir, "themes"))]

    for item_type, path in items:
        if not os.path.exists(path):
            continue

        slugs = os.listdir(path)

        for slug in tqdm(slugs, desc=f"Auditing {item_type}s"):
            item_path = os.path.join(path, slug)
            output_file = os.path.join(item_path, "semgrep_output.json")

            command = [
                "semgrep",
                "--config",
                "{}".format(config),
                "--json",
                "--no-git-ignore",
                "--output",
                output_file,
                "--quiet",  # Suppress non-essential output
                item_path,
            ]

            try:
                # Run the semgrep command
                subprocess.run(command, check=True)
                if verbose:
                    print(f"Semgrep analysis completed for {item_type} {slug}.")

            except subprocess.CalledProcessError as e:
                print(f"Semgrep failed for {item_type} {slug}: {e}")
                continue

            # Read the output file and process results
            try:
                with open(output_file, "r") as file:
                    data = json.load(file)
                    for result in data.get("results", []):
                        insert_result_into_db(cursor, slug, result, item_type=item_type)
                    db_conn.commit()
            except json.JSONDecodeError as e:
                print(f"Failed to decode JSON for {item_type} {slug}: {e}")
            except Exception as e:
                print(f"Unexpected error for {item_type} {slug}: {e}")

def parse_date(date_str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Downloads or audits WordPress plugins and themes with >= 1,000 active installations."
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download and extract plugins and themes.",
    )
    parser.add_argument(
        "--download-dir",
        type=str,
        default=".",
        help="The directory to save/audit downloaded items (default: current directory)",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Audits downloaded plugins and themes sequentially",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="p/php",
        help="Semgrep config/rules to run (default: p/php)",
    )
    parser.add_argument(
        "--create-schema",
        action="store_true",
        help="Create the database and schema if this flag is set",
    )
    parser.add_argument(
        "--clear-results",
        action="store_true",
        help="Clear audit results tables before running",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print detailed messages"
    )

    # Parse arguments
    args = parser.parse_args()

    if not args.download and not args.audit:
        print("Please set either the --download or --audit option.\n")
        parser.print_help()
        sys.exit(1)
    else:
        # Connect to the database
        db_conn, cursor = connect_to_db(args.create_schema)
        if args.clear_results:
            delete_results_table(cursor)
            db_conn.commit()

        # Write plugins and themes to DB and possibly download them
        if args.download:
            write_plugins_to_db_and_download(
                db_conn, cursor, args.download_dir, args.verbose
            )
            write_themes_to_db_and_download(
                db_conn, cursor, args.download_dir, args.verbose
            )
        if args.audit:
            run_semgrep_and_store_results(
                db_conn, cursor, args.download_dir, args.config, args.verbose
            )

        cursor.close()
        db_conn.close()

