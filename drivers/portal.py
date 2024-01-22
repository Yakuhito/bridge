from drivers.utils import load_clvm_hex
from chia.types.blockchain_format.program import Program
from chia.wallet.puzzles.singleton_top_layer_v1_1 import \
    SINGLETON_LAUNCHER_HASH
from chia.wallet.puzzles.singleton_top_layer_v1_1 import SINGLETON_MOD_HASH
from chia.types.blockchain_format.sized_bytes import bytes32
from chia_rs import G1Element
from chia.wallet.puzzles.singleton_top_layer_v1_1 import puzzle_for_singleton
from typing import List
from chia.types.blockchain_format.coin import Coin

MESSAGE_COIN_MOD = load_clvm_hex("puzzles/message_coin.clsp")
PORTAL_RECEIVER_MOD = load_clvm_hex("puzzles/portal_receiver.clsp")

def get_message_coin_puzzle_1st_curry(portal_receiver_launcher_id: bytes32) -> Program:
    return MESSAGE_COIN_MOD.curry(SINGLETON_MOD_HASH, SINGLETON_LAUNCHER_HASH, portal_receiver_launcher_id)

def get_message_coin_puzzle(
    portal_receiver_launcher_id: bytes32,
    sender: bytes,
    target: bytes32,
    target_is_puzzle_hash: bool,
    deadline: int,
    message_hash: bytes32
) -> Program:
  return get_message_coin_puzzle_1st_curry(portal_receiver_launcher_id).curry(
    sender,
    target,
    target_is_puzzle_hash,
    deadline,
    message_hash
  )

def get_portal_receiver_inner_puzzle(
      launcher_id: bytes32,
      signature_treshold: int,
      signature_pubkeys: list[G1Element],
      last_nonces: List[int] = [],
) -> Program:
    first_curry = PORTAL_RECEIVER_MOD.curry(
      (signature_treshold, signature_pubkeys), # VALIDATOR_INFO
      get_message_coin_puzzle_1st_curry(launcher_id).get_tree_hash()
    )

    return first_curry.curry(
      first_curry.get_tree_hash(), # SELF_HASH
      last_nonces
    )

def get_portal_receiver_full_puzzle(
      launcher_id: bytes32,
      signature_treshold: int,
      signature_pubkeys: List[G1Element],
      last_nonces: List[int] = [],
) -> Program:
  return puzzle_for_singleton(
     launcher_id,
     get_portal_receiver_inner_puzzle(launcher_id, signature_treshold, signature_pubkeys, last_nonces),
  )

class PortalMessage:
    nonce: int
    validator_sig_switches: List[bool]
    sender: bytes
    target: bytes32
    target_is_puzzle_hash: bool
    deadline: int
    message: Program

def get_portal_receiver_inner_solution(
    new_inner_puzzle_hash: bytes32,
    messages: List[PortalMessage],
) -> Program:
    return Program.to([
       new_inner_puzzle_hash,
       [message.nonce for message in messages],
       [
          [
              msg.validator_sig_switches,
              msg.sender,
              msg.target,
              msg.target_is_puzzle_hash,
              msg.deadline,
              msg.message
          ] for msg in messages
       ]
    ])

def get_message_coin_solution(
    receiver_coin: Coin,
    parent_parent_info: bytes32,
    parent_inner_puzzle_hash: bytes32,
    message_coin_id: bytes32,
    receiver_singleton_launcher_id: bytes32 | None = None,
    receiver_singleton_inner_puzzle_hash: bytes32 | None = None,
) -> Program:
    return Program.to([
      (receiver_coin.parent_coin_info, (receiver_coin.puzzle_hash, receiver_coin.amount)),
      0 if receiver_singleton_launcher_id is None and receiver_singleton_inner_puzzle_hash is None else (receiver_singleton_launcher_id, receiver_singleton_inner_puzzle_hash),
      (parent_parent_info, parent_inner_puzzle_hash),
      message_coin_id
    ])
