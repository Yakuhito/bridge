# note from yak: this file is ungly, but it works.
import click
import json
from web3 import Web3
from commands.config import get_config_item
from chia.wallet.trading.offer import Offer, OFFER_MOD
from chia.types.blockchain_format.program import Program
from chia.types.spend_bundle import SpendBundle
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.types.condition_opcodes import ConditionOpcode
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_LAUNCHER_HASH, SINGLETON_LAUNCHER, launch_conditions_and_coinsol
from chia.wallet.puzzles.singleton_top_layer_v1_1 import pay_to_singleton_puzzle
from chia.util.keychain import bytes_to_mnemonic, mnemonic_to_seed
from commands.keys import mnemonic_to_validator_pk
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_spend import CoinSpend
from drivers.multisig import get_multisig_inner_puzzle
from drivers.portal import *
from drivers.wrapped_assets import get_cat_minter_puzzle, get_cat_burner_puzzle
from chia.wallet.puzzles.p2_delegated_conditions import puzzle_for_pk, solution_for_conditions
from commands.config import get_config_item
from chia_rs import G1Element, AugSchemeMPL
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from typing import Tuple
import hashlib
import secrets
import json
from commands.cli_wrappers import async_func

@click.group()
def deployment():
    pass

def predict_create2_address(sender, salt, init_code):
    sender_address_bytes = Web3.to_bytes(hexstr=sender)
    salt_bytes = Web3.to_bytes(salt) if isinstance(salt, str) else salt
    init_code_bytes = Web3.to_bytes(hexstr=init_code)
    
    create2_prefix = b'\xff'
    create2_inputs = create2_prefix + sender_address_bytes + salt_bytes + Web3.keccak(init_code_bytes)
    create2_hash = Web3.keccak(create2_inputs)
    
    contract_address_bytes = create2_hash[12:]
    
    contract_address = Web3.to_checksum_address(contract_address_bytes)
    return contract_address

@deployment.command()
@click.option('--weth-address', required=True, help='WETH contract address to be used by the bridge')
def get_eth_deployment_data(weth_address):
    click.echo("Constructing txes based on config...")
    wei_per_message_fee = get_config_item(["eth", "wei_per_message_fee"])

    w3 = Web3(Web3.HTTPProvider(get_config_item(["eth", "rpc_url"])))

    portal_artifact = json.loads(
        open('artifacts/contracts/Portal.sol/Portal.json', 'r').read()
      )
    eth_token_bridge_artifact = json.loads(
        open('artifacts/contracts/EthTokenBridge.sol/EthTokenBridge.json', 'r').read()
      )
    proxy_artifact = json.loads(
        open('artifacts/@openzeppelin/contracts/proxy/transparent/TransparentUpgradeableProxy.sol/TransparentUpgradeableProxy.json', 'r').read()
      )
    
    deployer_safe_address = get_config_item(["eth", "deployer_safe_address"])
    create_call_address = get_config_item(["eth", "create_call_address"])

    salt = hashlib.sha256(b"you cannot imagine how often yakuhito manually changed this salt source").digest()

    portal_contract = w3.eth.contract(
        abi=portal_artifact['abi'],
        bytecode=portal_artifact['bytecode']
    )
    portal_constructor_data = portal_contract.constructor().build_transaction()['data']
    open("portal_constructor.data", "w").write(portal_constructor_data)

    portal_logic_address = predict_create2_address(create_call_address, salt, portal_constructor_data)

    portal_initialization_data = portal_initialization_data = portal_contract.encodeABI(
        fn_name='initialize',
        args=[
            Web3.to_bytes(hexstr=deployer_safe_address),
            wei_per_message_fee,
            [Web3.to_bytes(hexstr=addr) for addr in get_config_item(["eth", "hot_addresses"])],
            get_config_item(["eth", "portal_threshold"])
        ]
    )
    proxy_constructor_data = w3.eth.contract(
        abi=proxy_artifact['abi'],
        bytecode=proxy_artifact['bytecode']
    ).constructor(
        Web3.to_bytes(hexstr=portal_logic_address),
        Web3.to_bytes(hexstr=deployer_safe_address),
        portal_initialization_data
    ).build_transaction({
        'gas': 5000000000
    })['data']
    open("proxy_constructor.data", "w").write(proxy_constructor_data)

    portal_address = predict_create2_address(create_call_address, salt, proxy_constructor_data)

    eth_token_bridge_constructor_data = w3.eth.contract(
        abi=eth_token_bridge_artifact['abi'],
        bytecode=eth_token_bridge_artifact['bytecode']
    ).constructor(
        Web3.to_bytes(hexstr=portal_address),
        Web3.to_bytes(hexstr=deployer_safe_address),
        Web3.to_bytes(hexstr=weth_address)
    ).build_transaction({
        'gas': 5000000000
    })['data']
    open("eth_token_bridge_constructor.data", "w").write(eth_token_bridge_constructor_data)

    print("")
    print("")
    print("Deployment batch #1")
    print("-------------------")
    print("Tx 1: deploy Portal")
    print(f"\t To: {create_call_address}")
    print(f"\t Contract method selector: performCreate2")
    print(f"\t Value: 0")
    print(f"\t Data: see portal_constructor.data")
    print(f"\t Salt: 0x{salt.hex()}")
    print(f"\t Predicted address: {portal_logic_address}")

    print("Tx 2: deploy TransparentUpgradeableProxy")
    print(f"\t To: {create_call_address}")
    print(f"\t Contract method selector: performCreate2")
    print(f"\t Value: 0")
    print(f"\t Data: see proxy_constructor.data")
    print(f"\t Salt: 0x{salt.hex()}")
    print(f"\t Predicted address: {portal_address}")

    print("Tx 3: deploy EthTokenBridge")
    print(f"\t To: {create_call_address}")
    print(f"\t Contract method selector: performCreate2")
    print(f"\t Value: 0")
    print(f"\t Data: see eth_token_bridge_constructor.data")
    print(f"\t Salt: 0x{salt.hex()}")
    print(f"\t Predicted address: {predict_create2_address(create_call_address, salt, eth_token_bridge_constructor_data)}")


async def securely_launch_singleton(
    offer: Offer,
    get_target_singleton_inner_puzze: any,
    comments: List[Tuple[str, str]] = []
) -> Tuple[bytes32, SpendBundle]: # launcher_id, spend_bundle
    offer_sb: SpendBundle = offer.to_spend_bundle()
    coin_spends = []
    for cs in offer_sb.coin_spends:
        if cs.coin.parent_coin_info != b'\x00' * 32:
            coin_spends.append(cs)

    # create launcher parent parent coin
    # this coin makes it impossible for the singleton to have the predicted launcher id
    # unless it has exactly the intended ph
    entropy = secrets.token_bytes(16)
    mnemonic = bytes_to_mnemonic(entropy)
    temp_private_key = mnemonic_to_validator_pk(mnemonic)
    temp_public_key = temp_private_key.get_g1()
            
    launcher_parent_puzzle = puzzle_for_pk(Program.to(temp_public_key))
    launcher_parent_puzzle_hash = launcher_parent_puzzle.get_tree_hash()

    nonce = secrets.token_bytes(32)
    launcher_parent_parent = offer.get_offered_coins()[None][0]
    launcher_parent_parent_puzzle = OFFER_MOD
    launcher_parent_parent_solution = Program.to([
        [nonce, [launcher_parent_puzzle_hash, 1]]
    ])
    launcher_parent_parent_spend = CoinSpend(launcher_parent_parent, launcher_parent_parent_puzzle, launcher_parent_parent_solution)
    coin_spends.append(launcher_parent_parent_spend)

    # spend launcher coin
    launcher_parent = Coin(
        launcher_parent_parent.name(),
        launcher_parent_puzzle_hash,
        1
    )
    launcher_coin = Coin(
        launcher_parent.name(),
        SINGLETON_LAUNCHER_HASH,
        1
    )

    launcher_id = launcher_coin.name()
    click.echo(f"Launcher coin id: {launcher_id.hex()}")

    conditions, launcher_spend = launch_conditions_and_coinsol(
        launcher_parent,
        get_target_singleton_inner_puzze(launcher_id),
        comments,
        1
    )
    coin_spends.append(launcher_spend)

    # finally, spend launcher parent
    launcher_parent_solution = solution_for_conditions(Program.to(conditions))
    launcher_parent_spend = CoinSpend(launcher_parent, launcher_parent_puzzle, launcher_parent_solution)
    coin_spends.append(launcher_parent_spend)

    def just_return_the_fing_key(arg: any):
        return temp_private_key

    sb_just_for_sig: SpendBundle = await sign_coin_spends(
        [launcher_parent_spend],
        just_return_the_fing_key,
        just_return_the_fing_key,
        bytes.fromhex(get_config_item(["xch", "agg_sig_data"])),
        DEFAULT_CONSTANTS.MAX_BLOCK_COST_CLVM,
        []
    )
    sig = sb_just_for_sig.aggregated_signature
            
    sb = SpendBundle(
        coin_spends,
        AugSchemeMPL.aggregate([offer_sb.aggregated_signature, sig])
    )
    open("sb.json", "w").write(json.dumps(sb.to_json_dict(), indent=4))
    open("push_request.json", "w").write(json.dumps({"spend_bundle": sb.to_json_dict()}, indent=4))

    click.echo("SpendBundle created and saved to sb.json")
    click.echo("To spend: chia rpc full_node push_tx -j push_request.json")
    click.echo("To follow in mempool: chia rpc full_node get_mempool_items_by_coin_name '{\"coin_name\": \"" + launcher_id.hex() + "\"}'")
    click.echo("To confirm: chia rpc full_node get_coin_record_by_name '{\"name\": \"" + launcher_id.hex() + "\"}'")

    return [launcher_id, sb]


# chia rpc wallet create_offer_for_ids '{"offer":{"1":-1},"fee":4200000000,"driver_dict":{},"validate_only":false}'
@deployment.command()
@click.option('--offer', default="help", help='Offer to build a multisig from (must offer  exactly 1 mojo + include min network fee)')
@async_func
async def launch_xch_multisig(offer):
    if offer == "help":
        click.echo("Oops, you forgot --offer!")
        click.echo('chia rpc wallet create_offer_for_ids \'{"offer":{"1":-1},"fee":4200000000,"driver_dict":{},"validate_only":false}\'')
        return
    offer = Offer.from_bech32(offer)

    threshold = get_config_item(["xch", "multisig_threshold"])
    pks = get_config_item(["xch", "multisig_keys"])
    pks = [G1Element.from_bytes(bytes.fromhex(pk)) for pk in pks]
    multisig_inner_puzzle = get_multisig_inner_puzzle(pks, threshold)

    def get_multisig_inner_puzzle_pls(launcher_id: bytes32):
        return multisig_inner_puzzle
    
    launcher_id, _ = await securely_launch_singleton(
        offer,
        get_multisig_inner_puzzle_pls,
        [("yep", "multisig")]
    )
    p2_puzzle_hash = pay_to_singleton_puzzle(launcher_id).get_tree_hash()
    click.echo(f"One last thing - p2_multisig puzzle (bridging ph) is {p2_puzzle_hash.hex()}")


# chia rpc wallet create_offer_for_ids '{"offer":{"1":-1},"fee":4200000000,"driver_dict":{},"validate_only":false}'
@deployment.command()
@click.option('--offer', default="help", help='Offer to build a multisig from (must offer  exactly 1 mojo + include min network fee)')
@async_func
async def launch_xch_portal(offer):
    if offer == "help":
        click.echo("Oops, you forgot --offer!")
        click.echo('chia rpc wallet create_offer_for_ids \'{"offer":{"1":-1},"fee":4200000000,"driver_dict":{},"validate_only":false}\'')
        return
    offer = Offer.from_bech32(offer)
    
    portal_threshold = get_config_item(["xch", "portal_threshold"])
    portal_pks = [G1Element.from_bytes(bytes.fromhex(pk)) for pk in get_config_item(["xch", "portal_keys"])]
    multisig_threshold = get_config_item(["xch", "multisig_threshold"])
    multisig_pks = [G1Element.from_bytes(bytes.fromhex(pk)) for pk in get_config_item(["xch", "multisig_keys"])]

    def get_portal_receiver_inner_puzzle_pls(launcher_id: bytes32):
        return get_portal_receiver_inner_puzzle(
            launcher_id,
            portal_threshold,
            portal_pks,
            get_multisig_inner_puzzle(multisig_pks, multisig_threshold).get_tree_hash()
        )

    await securely_launch_singleton(
        offer,
        get_portal_receiver_inner_puzzle_pls,
        [("the", "portal")]
    )

@deployment.command()
@click.option('--for-chain', default="eth", help='Source/destination blockchain config entry')
def get_xch_info(for_chain: str):
    multisig_launcher_id = bytes.fromhex(get_config_item(["xch", "multisig_launcher_id"]))
    portal_launcher_id = bytes.fromhex(get_config_item(["xch", "portal_launcher_id"]))
    portal_threshold = get_config_item(["xch", "portal_threshold"])

    p2_multisig = pay_to_singleton_puzzle(multisig_launcher_id).get_tree_hash()

    minter_puzzle = get_cat_minter_puzzle(
        portal_launcher_id,
        p2_multisig,
        for_chain.encode(),
        bytes.fromhex(get_config_item([for_chain, "eth_token_bridge_address"]).replace("0x", ""))
    )

    burner_puzzle = get_cat_burner_puzzle(
        p2_multisig,
        for_chain.encode(),
        bytes.fromhex(get_config_item([for_chain, "eth_token_bridge_address"]).replace("0x", ""))
    )

    click.echo(f"Portal launcher id: {portal_launcher_id.hex()}")
    click.echo(f"Portal signature threshold: {portal_threshold}")
    click.echo(f"Burner puzzle hash: {burner_puzzle.get_tree_hash().hex()}")
    click.echo(f"Minter puzzle hash: {minter_puzzle.get_tree_hash().hex()}")
