import click
from commands.cli_wrappers import *
from chia.rpc.full_node_rpc_client import FullNodeRpcClients
from chia.wallet.puzzles.singleton_top_layer_v1_1 import pay_to_singleton_puzzle
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from typing import List
import json

@click.group()
def multisig():
    pass

COIN_ID_SAVE_FILE = "last_spent_multisig_coinid"

@multisig.command()
@click.option('--payout-structure-file', required=True, help='JSON file containing {address: share}')
@async_func
@with_node
async def start_new_spend(
    node: FullNodeRpcClient,
    payout_structure_file: str
):
    click.echo("Finding coins...")
    launcher_id = get_config_item(["chia", "multisig_launcher_id"])
    launcher_id: bytes32 = bytes.fromhex(launcher_id)
    p2_puzzle_hash = pay_to_singleton_puzzle(launcher_id).get_tree_hash()
    click.echo(f"p2_puzzle_hash: {p2_puzzle_hash.hex()}")

    p2_puzzle_hash_verify = get_config_item(["chia", "bridging_ph"])
    if p2_puzzle_hash.hex() != p2_puzzle_hash_verify:
        click.echo("Oops! p2_puzzle_hash mismatch :(")
        return

    coin_records: List[CoinRecord] = await node.get_coin_records_by_puzzle_hash(p2_puzzle_hash, include_spent_coins=False)

    # in case someone tries to be funny
    # filter_amount = get_config_item(["chia", "per_message_fee"])
    # coin_records = [cr for cr in coin_records if cr.coin.amount == filter_amount]

    if len(coin_records) == 0:
        click.echo("No claimable coins found :(")
        return
    
    click.echo("Found coins:")
    for cr in coin_records:
        click.echo(f"{cr.coin.name().hex()} -> {cr.coin.amount / 10 ** 12} XCH")

    click.echo(f"In total, there are {len(coin_records)} coins with a total value of {sum([cr.coin.amount for cr in coin_records]) / 10 ** 12} XCH.")

    value = input("In XCH, how much would you like to collect? ")
    value = int(float(value) ** 10 ** 12)

    fee = input("In XCH, what fee should the claim tx have? ")
    fee = int(float(value) ** 10 ** 12)

    total_value = value + fee

    max_coins = 200
    to_claim = []
    for cr in coin_records[:max_coins]:
        total_value -= cr.coin.amount
        to_claim.append(cr)
        if total_value < 0:
            break
        
    click.echo(f"Selected {len(to_claim)} claimable coins with a total value of {sum([cr.coin.amount for cr in to_claim]) / 10 ** 12} XCH.")
    
    payout_structure = json.loads(open(payout_structure_file, "r").read())
    click.echo("Payout structure data loaded.")

    click.echo("One last thing: finding latest spent multisig coin...")
    latest_coin = await get_latest_spent_multisig_coin(node)

    click.echo(f"Latest spent multisig coin: {latest_coin.name().hex()}")

    coins_to_claim = {}
    for cr in to_claim:
        coins_to_claim[cr.coin.name().hex()] = cr.coin.amount
    open("unsigned_transaction.json", "w").write(json.dumps({
        "multisig_parent": latest_coin.name().hex(),
        "payout_structure": payout_structure,
        "coins": coins_to_claim,
    }))
    click.echo("Done! Unsigned transaction saved to unsigned_transaction.json")