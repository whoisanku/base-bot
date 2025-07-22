console.log("Script starting...");
import "dotenv/config";
import { http, createPublicClient, parseAbiItem } from "viem";
import { base } from "viem/chains";
import { exec } from "child_process";

// ────────────────────────────────────────────────────────────
// CONFIG
// ────────────────────────────────────────────────────────────
const { RPC_URL } = process.env;
const POLLING_INTERVAL = 2000; // 2 seconds
const TARGET_ADDRESS =
  "0xA3296bAEB33c2D5dF1AB417E1a805Dd63D8C3BE3".toLowerCase();
const MIN_TOKEN_AMOUNT = 10_000_000n * 10n ** 18n; // 10M tokens with 18 decimals

// ────────────────────────────────────────────────────────────
// VIEM
// ────────────────────────────────────────────────────────────
const publicCli = createPublicClient({
  transport: http(RPC_URL),
  chain: base,
});

async function getLatestBlock() {
  return await publicCli.getBlockNumber();
}

async function getTokenTransferLogs(fromBlock: bigint, toBlock: bigint) {
  return await publicCli.getLogs({
    address: undefined, // All addresses
    event: parseAbiItem(
      "event Transfer(address indexed from, address indexed to, uint256 value)"
    ),
    args: {
      to: TARGET_ADDRESS as `0x${string}`,
    },
    fromBlock,
    toBlock,
  });
}

function isValidTransfer(log: any) {
  const value = log.args.value;
  return value >= MIN_TOKEN_AMOUNT;
}

function triggerBuy(tokenAddress: string) {
  console.log(`🚀 Triggering buy for token: ${tokenAddress}`);
  const command = `node dist/src/send.js --buy-token ${tokenAddress}`;

  exec(command, (error, stdout, stderr) => {
    if (error) {
      console.error(`exec error: ${error}`);
      return;
    }
    console.log(`stdout: ${stdout}`);
    console.error(`stderr: ${stderr}`);
  });
}

async function run() {
  console.log("Starting Base Token Monitor...");
  let lastBlock = await getLatestBlock();

  while (true) {
    try {
      const latestBlock = await getLatestBlock();

      if (lastBlock < latestBlock) {
        console.log(
          `Scanning blocks from ${lastBlock + 1n} to ${latestBlock}...`
        );
        const logs = await getTokenTransferLogs(lastBlock + 1n, latestBlock);

        if (logs) {
          for (const log of logs) {
            if (isValidTransfer(log)) {
              console.log(`Valid transfer found:`, log);
              triggerBuy(log.address);
            }
          }
        }
        lastBlock = latestBlock;
      }

      await new Promise((resolve) => setTimeout(resolve, POLLING_INTERVAL));
    } catch (error) {
      console.error("An error occurred in the main loop:", error);
      await new Promise((resolve) => setTimeout(resolve, 10000)); // Wait longer after an error
    }
  }
}

run();
