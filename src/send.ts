console.log("Script starting...");
import "dotenv/config";
import {
  http,
  createWalletClient,
  createPublicClient,
  parseEther,
  parseUnits,
  encodeFunctionData,
  parseAbi,
} from "viem";
import { base } from "viem/chains";
import { privateKeyToAccount } from "viem/accounts";
import { toSimpleSmartAccount } from "permissionless/accounts";
import { createSmartAccountClient } from "permissionless";
import { getUserOperationGasPrice } from "permissionless/actions/pimlico";
import {
  createTradeCall,
  type TradeParameters,
  setApiKey,
} from "@zoralabs/coins-sdk";
import type { Address, Hex } from "viem";

// ────────────────────────────────────────────────────────────
// CONFIG ─ edit these or pass via CLI flags
// ────────────────────────────────────────────────────────────
const buyTokenArgIndex = process.argv.indexOf("--buy-token");
let CONTENT_TOKEN: `0x${string}`;
const DESTINATION: Address = "0xA3296bAEB33c2D5dF1AB417E1a805Dd63D8C3BE3";

if (buyTokenArgIndex !== -1 && process.argv.length > buyTokenArgIndex + 1) {
  CONTENT_TOKEN = process.argv[buyTokenArgIndex + 1] as `0x${string}`;
} else {
  throw new Error("❌ Missing --buy-token address argument.");
}


const AMOUNT_ETH = 0.0025; // default if selling ETH
const AMOUNT_ERC20 = 10; // default if selling ERC‑20
const ERC20_DEC = 6; // decimals for the ERC‑20 you sell
const SELL_ERC20 = process.argv.includes("--erc20");

// ────────────────────────────────────────────────────────────
// ENV sanity
// ────────────────────────────────────────────────────────────
const { PRIVATE_KEY, RPC_URL, PIMLICO_API_KEY, ZORA_API_KEY } = process.env;
if (!PRIVATE_KEY || !RPC_URL || !PIMLICO_API_KEY || !ZORA_API_KEY) {
  throw new Error(
    "❌ Missing one of PRIVATE_KEY, RPC_URL, PIMLICO_API_KEY, ZORA_API_KEY in .env"
  );
}
setApiKey(ZORA_API_KEY);

// ────────────────────────────────────────────────────────────
// Smart account bootstrap
// ────────────────────────────────────────────────────────────
const eoa = privateKeyToAccount(`0x${PRIVATE_KEY}`);

const walletCli = createWalletClient({
  transport: http(RPC_URL),
  account: eoa,
  chain: base,
});
const simpleAcc = await toSimpleSmartAccount({
  client: walletCli,
  owner: eoa,
  entryPoint: {
    address: "0x5FF137D4b0FDCD49DcA30c7CF57E578a026d2789",
    version: "0.6",
  },
});

const saClient = createSmartAccountClient({
  account: simpleAcc,
  chain: base,
  bundlerTransport: http(
    `https://api.pimlico.io/v2/${base.id}/rpc?apikey=${PIMLICO_API_KEY}`
  ),
});
console.log("Smart account:", simpleAcc.address);

// ────────────────────────────────────────────────────────────
// Build trade with Zora Coins SDK
// ────────────────────────────────────────────────────────────
let sellAsset: { type: "eth" } | { type: "erc20"; address: Address };
if (SELL_ERC20) {
  const sellErc20Addr = process.argv[process.argv.indexOf("--erc20") + 1];
  if (!sellErc20Addr) {
    throw new Error("❌ Missing ERC‑20 address, pass via --erc20 0x...");
  }
  sellAsset = { type: "erc20", address: sellErc20Addr as Address };
} else {
  sellAsset = { type: "eth" };
}

const amountIn = SELL_ERC20
  ? parseUnits(
      process.argv.includes("--amount")
        ? process.argv[process.argv.indexOf("--amount") + 1]
        : AMOUNT_ERC20.toString(),
      process.argv.includes("--decimals")
        ? Number(process.argv[process.argv.indexOf("--decimals") + 1])
        : ERC20_DEC
    )
  : parseEther(
      process.argv.includes("--amount")
        ? process.argv[process.argv.indexOf("--amount") + 1]
        : AMOUNT_ETH.toString()
    );

const publicCli = createPublicClient({
  transport: http(RPC_URL),
  chain: base,
});
const balance = await publicCli.getBalance({ address: simpleAcc.address });
console.log(`Smart account balance: ${balance} wei`);

if (balance === 0n) {
  console.error(
    `❌ Smart account has no balance. Please send some Base ETH to ${simpleAcc.address}`
  );
  process.exit(1);
}

const tradeParams: TradeParameters = {
  sell: sellAsset,
  buy: { type: "erc20", address: CONTENT_TOKEN },
  amountIn,
  slippage: 0.05, // 50% slippage for debugging
  sender: simpleAcc.address,
};

const quote = await createTradeCall(tradeParams);
console.log("Settler:", quote.call.target);

// ────────────────────────────────────────────────────────────
// Build final calldata & target
// ────────────────────────────────────────────────────────────
const addr = (s: string) => s as Address;
const bytes = (s: string) => s as Hex;

let to: Address;
let data: Hex;
let value: bigint;

if (sellAsset.type === "eth") {
  // direct call
  to = addr(quote.call.target);
  data = bytes(quote.call.data);
  value = BigInt(quote.call.value);
} else {
  // one‑time allowance via AllowanceHolder.exec
  const execAbi = parseAbi([
    "function exec(address operator,address token,uint256 amount,address target,bytes data) payable returns (bytes)",
  ]);
  data = encodeFunctionData({
    abi: execAbi,
    functionName: "exec",
    args: [
      addr(quote.call.target),
      addr(sellAsset.address),
      amountIn,
      addr(quote.call.target),
      bytes(quote.call.data),
    ],
  });
  to = "0x0000000000001fF3684f28c67538d4D072C22734"; // AllowanceHolder
  value = 0n;
}

// ────────────────────────────────────────────────────────────
// Send UserOperation
// ────────────────────────────────────────────────────────────
try {
  const gasPrices = await getUserOperationGasPrice(saClient as any);

  // ---- Get a gas estimate *on-chain* first
  const gas = await publicCli.estimateGas({
    account: simpleAcc.address, // from
    to, // Settler
    data,
    value, // for an ETH→token swap this is == amountIn
  });

  // ---- Bump it by ~20 % as safety‑margin
  const paddedGas = gas + gas / 5n;

  const hash = await saClient.sendTransaction({
    to,
    data,
    value,
    gas: paddedGas,
    maxFeePerGas: gasPrices.standard.maxFeePerGas,
    maxPriorityFeePerGas: gasPrices.standard.maxPriorityFeePerGas,
  });
  console.log("UserOp:", hash);
  console.log(`Track ➜ https://base.blockscout.com/tx/${hash}`);

  // ────────────────────────────────────────────────────────────
  // Wait for buy transaction confirmation
  // ────────────────────────────────────────────────────────────
  console.log("Waiting for buy transaction to be mined …");
  const buyReceipt = await publicCli.waitForTransactionReceipt({ hash });
  console.log(`✅ Buy mined in block ${buyReceipt.blockNumber}`);

  // ────────────────────────────────────────────────────────────
  // Transfer acquired tokens from Smart Account to EOA
  // ────────────────────────────────────────────────────────────
  const erc20Abi = parseAbi([
    "function balanceOf(address) view returns (uint256)",
    "function transfer(address,uint256) returns (bool)",
  ]);

  const tokenBalance = (await publicCli.readContract({
    address: CONTENT_TOKEN as Address,
    abi: erc20Abi,
    functionName: "balanceOf",
    args: [simpleAcc.address],
  })) as bigint;

  console.log(`Smart account holds ${tokenBalance.toString()} tokens`);
  console.log(`Will transfer to destination: ${DESTINATION}`);
  if (tokenBalance === 0n) {
    console.error("❌ No tokens to transfer – exiting.");
    process.exit(0);
  }

  const transferCalldata = encodeFunctionData({
    abi: erc20Abi,
    functionName: "transfer",
    args: [DESTINATION as Address, tokenBalance],
  });

  const transferGas = await publicCli.estimateGas({
    account: simpleAcc.address,
    to: CONTENT_TOKEN as Address,
    data: transferCalldata,
    value: 0n,
  });
  const paddedTransferGas = transferGas + transferGas / 5n;

  const gasPrices2 = await getUserOperationGasPrice(saClient as any);

  const transferHash = await saClient.sendTransaction({
    to: CONTENT_TOKEN as Address,
    data: transferCalldata,
    value: 0n,
    gas: paddedTransferGas,
    maxFeePerGas: gasPrices2.standard.maxFeePerGas,
    maxPriorityFeePerGas: gasPrices2.standard.maxPriorityFeePerGas,
  });
  console.log("Transfer UserOp:", transferHash);
  console.log(`Track transfer ➜ https://base.blockscout.com/tx/${transferHash}`);

  await publicCli.waitForTransactionReceipt({ hash: transferHash });
  console.log("✅ Token transfer confirmed!");
} catch (err) {
  console.error("Simulation / bundler error:", err);
  process.exit(1);
}
