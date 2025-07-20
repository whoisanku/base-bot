#!/usr/bin/env python3
"""
Uniswap v4 Token Trader for Base Chain using ERC-4337 (Account Abstraction)

This script executes a token swap on Uniswap v4 by sending a UserOperation 
to an ERC-4337 EntryPoint contract. It is designed to buy a specified token 
using WETH.

This script is complex and requires a bundler service to be running and funded
to process the UserOperation.
"""

import os
import time
import json
from dotenv import load_dotenv
from web3 import Web3, Account
# geth_poa_middleware was removed in web3.py 7.x; Base chain does not require it
import requests
from eth_account.messages import encode_defunct

# --- Configuration ---

# Get the absolute path to the .env file
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')

# Load environment variables from .env file
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)
else:
    print("Warning: .env file not found. Please create it with your credentials.")
    exit(1)

# Base RPC and Chain Configuration
RPC_URL = "https://mainnet.base.org"
CHAIN_ID = 8453

# User Credentials (loaded from .env)
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
SMART_WALLET_ADDRESS = os.getenv("SMART_WALLET_ADDRESS")
BUNDLER_RPC_URL = os.getenv("BUNDLER_RPC_URL") or ""
if not BUNDLER_RPC_URL:
    print("Error: BUNDLER_RPC_URL missing in .env – cannot relay UserOperations.")
    exit(1)

if not all([PRIVATE_KEY, SMART_WALLET_ADDRESS]):
    print("Error: PRIVATE_KEY or SMART_WALLET_ADDRESS not found in .env file.")
    exit(1)

# Uniswap and ERC-4337 Contract Addresses (for Base Mainnet)
# EntryPoint v0.7.0 on Base mainnet
ENTRY_POINT_ADDRESS = "0x0000000071727De22E5E9d8BAf0edAc6f37da032"
# This is a placeholder for the Uniswap v4 Pool Manager.
# You may need to find the correct address for the specific pool.
# Universal Router (v4) on Base mainnet
UNIVERSAL_ROUTER_ADDRESS = "0x198EF79F1F515F02dFE9e3115eD9fC07183f02fC"
# Permit2 contract (required for token approvals)
PERMIT2_ADDRESS = "0x000000000022D473030F116dDEE9F6B43aC78BA3"
# Wrapped ETH on Base
WETH_ADDRESS = "0x4200000000000000000000000000000000000006"

# --- ABIs (Simplified for this example) ---

# Minimal ERC20 ABI for approve & allowance
ERC20_ABI = json.loads("""
[
  {"name":"approve","type":"function","inputs":[{"name":"spender","type":"address"},{"name":"amount","type":"uint256"}],"outputs":[{"name":"","type":"bool"}],"stateMutability":"nonpayable"},
  {"name":"allowance","type":"function","inputs":[{"name":"owner","type":"address"},{"name":"spender","type":"address"}],"outputs":[{"name":"","type":"uint256"}],"stateMutability":"view"}
]
""")

# ABI for the ERC-4337 EntryPoint contract (v0.7)
ENTRY_POINT_ABI = json.loads("""
[
  {
    "inputs": [
      {
        "components": [
          {"name": "sender", "type": "address"},
          {"name": "nonce", "type": "uint256"},
          {"name": "factory", "type": "address"},
          {"name": "factoryData", "type": "bytes"},
          {"name": "callData", "type": "bytes"},
          {"name": "callGasLimit", "type": "uint256"},
          {"name": "verificationGasLimit", "type": "uint256"},
          {"name": "preVerificationGas", "type": "uint256"},
          {"name": "maxFeePerGas", "type": "uint256"},
          {"name": "maxPriorityFeePerGas", "type": "uint256"},
          {"name": "paymaster", "type": "address"},
          {"name": "paymasterData", "type": "bytes"},
          {"name": "paymasterVerificationGasLimit", "type": "uint256"},
          {"name": "paymasterPostOpGasLimit", "type": "uint256"},
          {"name": "signature", "type": "bytes"}
        ],
        "name": "ops",
        "type": "tuple[]"
      },
      {"name": "beneficiary", "type": "address"}
    ],
    "name": "handleOps",
    "outputs": [],
    "stateMutability": "nonpayable",
    "type": "function"
  },
  {
    "inputs": [{"name": "sender", "type": "address"}, {"name": "key", "type": "uint192"}],
    "name": "getNonce",
    "outputs": [{"name": "nonce", "type": "uint256"}],
    "stateMutability": "view",
    "type": "function"
  },
  {
    "inputs": [
      {
        "components": [
          {"name": "sender", "type": "address"},
          {"name": "nonce", "type": "uint256"},
          {"name": "factory", "type": "address"},
          {"name": "factoryData", "type": "bytes"},
          {"name": "callData", "type": "bytes"},
          {"name": "callGasLimit", "type": "uint256"},
          {"name": "verificationGasLimit", "type": "uint256"},
          {"name": "preVerificationGas", "type": "uint256"},
          {"name": "maxFeePerGas", "type": "uint256"},
          {"name": "maxPriorityFeePerGas", "type": "uint256"},
          {"name": "paymaster", "type": "address"},
          {"name": "paymasterData", "type": "bytes"},
          {"name": "paymasterVerificationGasLimit", "type": "uint256"},
          {"name": "paymasterPostOpGasLimit", "type": "uint256"},
          {"name": "signature", "type": "bytes"}
        ],
        "name": "userOp",
        "type": "tuple"
      }
    ],
    "name": "getUserOpHash",
    "outputs": [{"name": "", "type": "bytes32"}],
    "stateMutability": "view",
    "type": "function"
  }
]
""")

# Minimal ABI for Universal Router `execute`
UNIVERSAL_ROUTER_ABI = json.loads("""
[
  {
    "inputs": [
      {"internalType": "bytes", "name": "commands", "type": "bytes"},
      {"internalType": "bytes[]", "name": "inputs", "type": "bytes[]"},
      {"internalType": "uint256", "name": "deadline", "type": "uint256"}
    ],
    "name": "execute",
    "outputs": [],
    "stateMutability": "payable",
    "type": "function"
  }
]
""")


class UniswapV4Trader:
    def __init__(self):
        self.web3 = Web3(Web3.HTTPProvider(RPC_URL))
        if not self.web3.is_connected():
            raise ConnectionError("Failed to connect to Base RPC")
        
        # EntryPoint & signer
        self.entry_point = self.web3.eth.contract(address=ENTRY_POINT_ADDRESS, abi=ENTRY_POINT_ABI)
        self.signer = Account.from_key(PRIVATE_KEY)

    def get_nonce(self):
        """Get the next nonce for the smart wallet from the EntryPoint."""
        # The key for getNonce is typically 0 for a standard EOA-owned smart wallet
        return self.entry_point.functions.getNonce(SMART_WALLET_ADDRESS, 0).call()

    def create_swap_calldata(self, token_to_buy, amount_in_eth):
        """Creates the callData for the swap operation."""
        # This is highly dependent on the specific Uniswap v4 pool and hooks.
        # The following is a generic placeholder and will likely need modification.
        
        # Dynamic import: eth_abi moved encode_abi between versions
        try:
            from eth_abi.abi import encode_abi  # eth-abi <4.0
        except (ImportError, ModuleNotFoundError):
            try:
                from eth_abi import encode as encode_abi  # eth-abi >=4.0 uses encode
            except ImportError:
                raise ImportError(
                    "eth_abi is missing encode function; please install/upgrade eth_abi package"
                )

        # 1. Build Universal Router commands
        V4_SWAP = 0x0B  # Command enum value for a v4 pool swap
        commands = bytes([V4_SWAP])

        # 2. Build the V4 swap action payload
        # For a single-pool exact-input swap the router expects:
        # (address tokenIn, address tokenOut, uint24 fee, address recipient,
        #  uint256 amountIn, uint256 amountOutMin, uint160 sqrtPriceLimitX96)
        # Official helper libraries encode this; here we hand-encode minimal fields.
        amount_in_wei = self.web3.to_wei(amount_in_eth, 'ether')
        swap_action = encode_abi(
            [
                'address',  # tokenIn (WETH)
                'address',  # tokenOut (token_to_buy)
                'uint24',   # fee (use 3000 = 0.3% as placeholder)
                'address',  # recipient (smart wallet)
                'uint256',  # amountIn
                'uint256',  # amountOutMin (0)
                'uint160'   # sqrtPriceLimitX96 (0)
            ],
            [
                WETH_ADDRESS,
                token_to_buy,
                3000,
                SMART_WALLET_ADDRESS,
                amount_in_wei,
                0,
                0
            ]
        )

        inputs = [swap_action]

        # 3. Encode Universal Router execute()
        router = self.web3.eth.contract(address=UNIVERSAL_ROUTER_ADDRESS, abi=UNIVERSAL_ROUTER_ABI)
        deadline = int(time.time()) + 300  # 5-minute validity
        router_calldata = router.encodeABI(fn_name="execute", args=[commands, inputs, deadline])

        return router_calldata

    def _user_op_to_tuple(self, user_op_dict):
        """Convert dict to the tuple struct expected by EntryPoint v0.7 ABI."""
        return (
            Web3.to_checksum_address(user_op_dict["sender"]),
            int(user_op_dict["nonce"]),
            Web3.to_checksum_address(user_op_dict["factory"]),
            Web3.to_bytes(hexstr=user_op_dict["factoryData"]),
            Web3.to_bytes(hexstr=user_op_dict["callData"]),
            int(user_op_dict["callGasLimit"]),
            int(user_op_dict["verificationGasLimit"]),
            int(user_op_dict["preVerificationGas"]),
            int(user_op_dict["maxFeePerGas"]),
            int(user_op_dict["maxPriorityFeePerGas"]),
            Web3.to_checksum_address(user_op_dict["paymaster"]),
            Web3.to_bytes(hexstr=user_op_dict["paymasterData"]),
            int(user_op_dict["paymasterVerificationGasLimit"]),
            int(user_op_dict["paymasterPostOpGasLimit"]),
            Web3.to_bytes(hexstr=user_op_dict["signature"]),
        )

    def sign_user_operation(self, user_op):
        """Hash the userOp via EntryPoint and sign it with the EOA key."""
        unsigned_op = user_op.copy()
        unsigned_op["signature"] = "0x"
        op_tuple = self._user_op_to_tuple(unsigned_op)
        op_hash = self.entry_point.functions.getUserOpHash(op_tuple).call()
        sig = self.signer.sign_message(encode_defunct(hexstr=op_hash.hex())).signature
        return sig.hex()

    def _format_user_op(self, op_dict):
        """Convert ints to hex strings for bundler."""
        fmt = {}
        for k, v in op_dict.items():
            if isinstance(v, int):
                fmt[k] = hex(v)
            else:
                fmt[k] = v
        return fmt

    def _send_to_bundler(self, signed_user_op: dict):
        """
        Sends a signed UserOperation to the configured bundler.
        Automatically chooses the right envelope for Biconomy vs. generic bundlers.
        """
        formatted = self._format_user_op(signed_user_op)   # hex‑string‑ify numbers

        # ------------ NEW CODE STARTS HERE ----------------------------------
        is_biconomy = "biconomy" in BUNDLER_RPC_URL.lower()
        print("entry point address", ENTRY_POINT_ADDRESS, formatted, is_biconomy)

        if is_biconomy:
            # 💡 Biconomy expects a wrapped object
            payload_params = [{"userOperation": formatted, "entryPointAddress": ENTRY_POINT_ADDRESS}]
        else:
            # Stackup / Pimlico / Alchemy style (array)
            payload_params = [formatted, ENTRY_POINT_ADDRESS]
        # ------------ NEW CODE ENDS HERE ------------------------------------

        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method": "eth_sendUserOperation",
            "params": payload_params
        }

        resp = requests.post(BUNDLER_RPC_URL, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _weth_allowance(self):
        weth = self.web3.eth.contract(address=WETH_ADDRESS, abi=ERC20_ABI)
        return weth.functions.allowance(SMART_WALLET_ADDRESS, PERMIT2_ADDRESS).call()

    def _build_approve_calldata(self):
        weth = self.web3.eth.contract(address=WETH_ADDRESS, abi=ERC20_ABI)
        MAX_UINT = (1 << 256) - 1
        return weth.encodeABI(fn_name="approve", args=[PERMIT2_ADDRESS, MAX_UINT])

    def buy_token(self, token_address, amount_eth_to_spend):
        """
        Constructs and sends a UserOperation to buy a token.
        NOTE: This function does not actually send the transaction. It prints the
        UserOperation that needs to be sent to a Bundler RPC endpoint.
        """
        print(f"Attempting to buy token: {token_address}")
        print(f"Amount to spend: {amount_eth_to_spend} ETH")
        
        # 1. Get the current nonce for the UserOperation
        nonce = self.get_nonce()
        print(f"Smart Wallet Nonce: {nonce}")

        # 2a. Ensure Permit2 allowance
        allowance = self._weth_allowance()
        if allowance == 0:
            print("WETH allowance for Permit2 is zero — generating approval UserOperation first.")
            approve_data = self._build_approve_calldata()
            call_data = self.web3.eth.contract(abi=[{"name":"execute","type":"function","inputs":[{"name":"target","type":"address"},{"name":"value","type":"uint256"},{"name":"data","type":"bytes"}],"outputs":[],"stateMutability":"payable"}]).encodeABI(
                fn_name="execute",
                args=[WETH_ADDRESS, 0, approve_data]
            )
            op_type = "PERMIT2_APPROVE"
        else:
            # 2b. Create the `callData` for the swap UserOperation.
            call_data = self.create_swap_calldata(token_address, amount_eth_to_spend)
            if call_data == "0x":
                print("Could not generate swap calldata. Aborting.")
                return
            op_type = "SWAP"

        # 3. Construct the UserOperation
        # Gas fees need to be estimated via a bundler (e.g., eth_estimateUserOperationGas)
        # Using placeholder values for demonstration.
        user_op = {
            "sender": SMART_WALLET_ADDRESS,
            "nonce": nonce,
            "factory": "0x0000000000000000000000000000000000000000",
            "factoryData": "0x",
            "callData": call_data,
            "callGasLimit": 500_000,  # Placeholder
            "verificationGasLimit": 200_000,  # Placeholder
            "preVerificationGas": 50_000,  # Placeholder
            "maxFeePerGas": self.web3.to_wei("2", "gwei"),  # Placeholder
            "maxPriorityFeePerGas": self.web3.to_wei("1", "gwei"),  # Placeholder
            "paymaster": "0x0000000000000000000000000000000000000000",
            "paymasterData": "0x",
            "paymasterVerificationGasLimit": 0,
            "paymasterPostOpGasLimit": 0,
            "signature": "0x",  # Will be added after signing
        }
        
        # 4. Sign the UserOperation (this part is complex and requires hashing off-chain)
        # For simplicity, we'll skip the real signing process in this example.
        # A proper implementation would hash the user_op and sign it.
        # signature = self.sign_user_operation(user_op)
        # user_op['signature'] = signature
        
        # 4. Sign & send
        user_op["signature"] = self.sign_user_operation(user_op)

        print("\n--- Signed UserOperation ---")
        print(json.dumps(user_op, indent=2))

        print("\n📡 Sending to bundler...")
        result = self._send_to_bundler(user_op)
        print("Bundler response:")
        print(json.dumps(result, indent=2))

