# dbutils.py

import mysql.connector
import configparser
from datetime import datetime


def connect_to_db(create_schema=False):
    # Read the configuration file
    config = configparser.ConfigParser()
    config.read("config.ini")

    # Extract database connection details
    db_config = config["database"]

    # Connect to the database server (initially without specifying the database)
    db_conn = mysql.connector.connect(
        host=db_config["host"],
        user=db_config["user"],
        password=db_config.get("password", ""),
    )
    cursor = db_conn.cursor()
    try:
        # If schema creation is requested, create the database and tables if they don't exist
        if create_schema:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_config['database']}")
            db_conn.database = db_config["database"]
            create_plugin_data_table(cursor)
            create_plugin_results_table(cursor)
            create_theme_data_table(cursor)
            create_theme_results_table(cursor)
        else:
            db_conn.database = db_config["database"]

    except mysql.connector.errors.ProgrammingError as e:
        if "1049" in str(e):
            raise SystemExit(
                f"Database {db_config['database']} does not exist. Please run with the '--create-schema' flag to create the database."
            )

    return db_conn, cursor


def delete_results_table(cursor):
    cursor.execute("DROP TABLE IF EXISTS PluginResults")
    create_plugin_results_table(cursor)
    # Commented out to avoid reprocessing themes
    cursor.execute("DROP TABLE IF EXISTS ThemeResults")
    create_theme_results_table(cursor)


def create_plugin_data_table(cursor):
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS PluginData (
        slug VARCHAR(255) PRIMARY KEY,
        version VARCHAR(255),
        active_installs INT,
        downloaded INT,
        last_updated DATETIME,
        added_date DATE,
        download_link TEXT
    )
    """
    )

def create_plugin_results_table(cursor):
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS PluginResults (
        id INT AUTO_INCREMENT PRIMARY KEY,
        slug VARCHAR(255),
        file_path VARCHAR(255),
        check_id VARCHAR(255),
        start_line INT,
        end_line INT,
        vuln_lines TEXT,
        FOREIGN KEY (slug) REFERENCES PluginData(slug)
    )
    """
    )

def create_theme_data_table(cursor):
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS ThemeData (
        slug VARCHAR(255) PRIMARY KEY,
        version VARCHAR(255),
        active_installs INT,
        downloaded INT,
        last_updated DATETIME,
        added_date DATE,
        download_link TEXT
    )
    """
    )

def create_theme_results_table(cursor):
    cursor.execute(
        """
    CREATE TABLE IF NOT EXISTS ThemeResults (
        id INT AUTO_INCREMENT PRIMARY KEY,
        slug VARCHAR(255),
        file_path VARCHAR(255),
        check_id VARCHAR(255),
        start_line INT,
        end_line INT,
        vuln_lines TEXT,
        FOREIGN KEY (slug) REFERENCES ThemeData(slug)
    )
    """
    )

def insert_plugin_into_db(cursor, plugin):
    sql = """
    INSERT INTO PluginData (slug, version, active_installs, downloaded, last_updated, added_date, download_link)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        version = VALUES(version),
        active_installs = VALUES(active_installs),
        downloaded = VALUES(downloaded),
        last_updated = VALUES(last_updated),
        added_date = VALUES(added_date),
        download_link = VALUES(download_link)
    """

    last_updated = plugin.get("modified", None)  # Use 'modified' instead of 'last_updated'
    added_date = plugin.get("added", None)

    # Convert date formats if available
    last_updated = parse_date_string(last_updated)
    added_date = parse_date_string(added_date, date_only=True)

    data = (
        plugin["slug"],
        plugin.get("version", "N/A"),
        int(plugin.get("active_installs", 0)),
        int(plugin.get("downloaded", 0)),
        last_updated,
        added_date,
        plugin.get("download_link", "N/A"),
    )

    try:
        cursor.execute(sql, data)
    except mysql.connector.errors.ProgrammingError as e:
        if "1146" in str(e):
            raise SystemExit(
                "Table does not exist. Please run with the '--create-schema' flag to create the table."
            )


def insert_theme_into_db(cursor, theme):
    sql = """
    INSERT INTO ThemeData (slug, version, active_installs, downloaded, last_updated, added_date, download_link)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        version = VALUES(version),
        active_installs = VALUES(active_installs),
        downloaded = VALUES(downloaded),
        last_updated = VALUES(last_updated),
        added_date = VALUES(added_date),
        download_link = VALUES(download_link)
    """

    last_updated = theme.get("last_updated", None)
    added_date = theme.get("added", None)

    # Convert date formats if available
    last_updated = parse_date_string(last_updated)
    added_date = parse_date_string(added_date, date_only=True)

    data = (
        theme["slug"],
        theme.get("version", "N/A"),
        int(theme.get("active_installs", 0)),
        int(theme.get("downloaded", 0)),
        last_updated,
        added_date,
        theme.get("download_link", "N/A"),
    )

    try:
        cursor.execute(sql, data)
    except mysql.connector.errors.ProgrammingError as e:
        if "1146" in str(e):
            raise SystemExit(
                "Table does not exist. Please run with the '--create-schema' flag to create the table."
            )

def insert_result_into_db(cursor, slug, result, item_type='plugin'):
    if item_type == 'plugin':
        table = 'PluginResults'
    # Commented out to avoid processing themes
    # elif item_type == 'theme':
    #     table = 'ThemeResults'
    else:
        raise ValueError("Invalid item_type. Must be 'plugin'.")

    sql = (
        f"INSERT INTO {table} (slug, file_path, check_id, start_line, end_line, vuln_lines)"
        " VALUES (%s, %s, %s, %s, %s, %s)"
    )
    data = (
        slug,
        result["path"],
        result["check_id"],
        result["start"]["line"],
        result["end"]["line"],
        result["extra"]["lines"],
    )
    try:
        cursor.execute(sql, data)
    except mysql.connector.errors.ProgrammingError as e:
        if "1146" in str(e):
            raise SystemExit(
                "Table does not exist. Please run with the '--create-schema' flag to create the table."
            )


def parse_date_string(date_str, date_only=False):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S") if not date_only else dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None
