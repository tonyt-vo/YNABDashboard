import influxdb
import json
import logging
import os
import requests
import sys
import time
import ynab_client
import ynab_resources
from utils import remove_emojis
from datetime import datetime, timedelta

# Configurations
config = "config.json"

# Execution
# Setup logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                    format="[%(asctime)s] %(levelname)s :: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger()

# Import and set all needed configurations
with open(os.path.join(sys.path[0], config)) as json_file:
    config_data = json.load(json_file)
idb_host = config_data["InfluxDBHost"]
idb_port = config_data["InfluxDBPort"]
idb_index = config_data["InfluxDBIndex"]
idb_user = config_data["InfluxDBUser"]
idb_pass = config_data["InfluxDBPass"]
ynab_api_key = config_data["YNAB_API_Key"]
ynab_budget_id = config_data["YNAB_Budget_ID"]

# Initiate connection to InfluxDB
influx_client = influxdb.InfluxDBClient(idb_host, idb_port, idb_user, idb_pass)

# Verify existence of required index
indices = influx_client.get_list_database()
if not any(index["name"] == idb_index for index in indices):
    influx_client.create_database(idb_index)
influx_client.switch_database(idb_index)

# Query for existing transaction data in InfluxDB
influx_query_transactions = (
    'SELECT * FROM "{}"."autogen"."transactions"'.format(idb_index))
influx_transactions_points = influx_client.query(
    influx_query_transactions).get_points(measurement='transactions')
influx_transactions_list = list(influx_transactions_points)
influx_transactions_ids = [i["id"] for i in influx_transactions_list]

# Configure and connect to YNAB
ynab_config = ynab_client.configuration(
    api_key=ynab_api_key, budget_id=ynab_budget_id)
ynab = ynab_client.connect(ynab_config)

# Get and parse budget data
# We'll only consider non-deleted accounts and categories
budget = ynab.get_budget_by_id_detailed(ynab_budget_id)
accounts = [a for a in budget.accounts if not a.deleted]
categories = [c for c in budget.categories if not c.deleted]
payees = budget.payees

# Get all our transations
all_transactions = [t for t in budget.transactions]

# TODO Handle split transactions where the category is nil
all_transactions_ids = [t.id for t in all_transactions]

# Consider our new and old transactions
new_transactions = [t for t in all_transactions if not any(
    t.id in id for id in influx_transactions_ids)]
bad_transactions = [i for i in influx_transactions_ids if not any(
    i in id for id in all_transactions_ids)]


def get_execution_time():
    """
    Get the current execution time
    @return [Date] The current time
    """
    return datetime.now().replace(minute=0, second=0, microsecond=0)


def generate_account_points(accounts):
    """
    Generate accounts points for the given accounts
    @param [Array] accounts The array of accounts 
    @return [Array] The array of accounts formatted in json format
    """
    points = []
    for account in accounts:
        account_json = {
            "measurement": "accounts",
            "time": get_execution_time().isoformat(),
            "tags": {
                "account": remove_emojis(account.name),
                "id": account.id,
                "budget": remove_emojis(budget.name),
                "type": account.type,
                "closed": account.closed,
                "deleted": account.deleted,
                "on_budget": account.on_budget
            },
            "fields": {
                "balance": account.balance,
                "unclearedBalance": account.cleared_balance,
                "clearedBalance": account.uncleared_balance
            }
        }
        points.append(account_json)
    return points


def generate_category_points(categories):
    """
    Generate category points for the given categories
    @param [Array] categories The array of categories
    @return [Array] The array of cateogires formatted in json format
    """
    points = []
    for category in categories:
        category_json = {
            "measurement": "categories",
            "time": get_execution_time().isoformat(),
            "tags": {
                "budget": remove_emojis(budget.name),
                "category": remove_emojis(category.name),
                "categoryGroup": remove_emojis(category.category_group_name),
                "goalType": category.goal_type,
                "goalTargetMonth": category.goal_target_month,
                "id": category.id,
                "deleted": category.deleted,
                "hidden": category.hidden
            },
            "fields": {
                "budgeted": category.budgeted,
                "activity": category.activity,
                "balance": category.balance,
                "goalTarget": category.goal_target,
                "goalPercentageComplete": category.goal_percentage_complete
            }
        }
        points.append(category_json)
    return points


def generate_transaction_points(transactions):
    """
    Generate transaction points for the given transactions
    @param [Array] transactions The array of transactions
    @return [Array] The array of transactions formatted in json format
    """
    points = []
    for transaction in transactions:
        transaction_json = {
            "measurement": "transactions",
            "time": transaction.date,
            "tags": {
                "account": remove_emojis(transaction.account_name),
                "budget": remove_emojis(budget.name),
                "category": remove_emojis(transaction.category_name),
                "categoryGroup": remove_emojis(transaction.category_group_name),
                "id": transaction.id,
                "payee": transaction.payee_name,
                "flagColor": transaction.flag_color
            },
            "fields": {
                "amount": transaction.amount,
                "memo": transaction.memo
            }
        }
        points.append(transaction_json)
    return points


points = []
points.extend(generate_account_points(accounts))
points.extend(generate_category_points(categories))
points.extend(generate_transaction_points(new_transactions))

# Remove bad points
for b in bad_transactions:
    tid_delete = "DELETE FROM \"transactions\" WHERE \"id\"='{}'".format(b)
    influx_client.query(tid_delete)

# Write all new points
influx_client.write_points(points)
