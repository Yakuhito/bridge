# XCH-Eth Bridge
### (and the other way around)

A Proof-of-Authority based cross-chain messaging protocol.

## Architecture

To connect the Chia and Ethereum blockchains, a trusted set of parties (validators) is needed. These parties each observe messages on one chain and relay it to the other. This repository also contains the code required to enable bridging tokens and native assets from Ethereum to Chia - the contracts are immutable, and rely on the bridge as an oracle. A fee is also given to the owner of the immutable contracts, presumably the bridge owners.

To ensure each message is unique, each side of the bridge assigns a nonce (a unique, increasing integer on Ethereum, a coin id on Chia) to each message. On the other side, the user has the ability to execute messages out-of-order, but can only use each message exactly once. A deadline can be used to specify an expiry timestamp after each a message will become invalid.

Bridge contracts are upgradeable by the validators to enable new functionality to be developed.

On Chia, messages are picked up by looking for the following output condition:

```
(list CREATE_COIN [bridge_specific_puzzle_hash] [amount] [sender_as_puzzle_hash] [target] [deadline] [message-list])
```
