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
// List of whitelisted target addresses (lower-case)
const WHITELISTED_ADDRESSES: string[] = [
  "0x2211d1D0020DAEA8039E46Cf1367962070d77DA9",
  "0x2B886875D17c51b3Cde74623D06e315f2994fA64",
  // "0xA3296bAEB33c2D5dF1AB417E1a805Dd63D8C3BE3",
  // Add more addresses below.
].map((a) => a.toLowerCase());
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
  const allLogs: any[] = [];
  for (const target of WHITELISTED_ADDRESSES) {
    try {
      const logs = await publicCli.getLogs({
        address: undefined,
        event: parseAbiItem(
          "event Transfer(address indexed from, address indexed to, uint256 value)"
        ),
        args: {
          to: target as `0x${string}`,
        },
        fromBlock,
        toBlock,
      });
      // annotate with target for debugging
      logs.forEach((l: any) => (l.targetAddress = target));
      allLogs.push(...logs);
    } catch (err) {
      console.error(`Error fetching logs for ${target}:`, err);
    }
  }
  return allLogs;
}

function isValidTransfer(log: any) {
  const value = log.args?.value;
  return value !== undefined && value >= MIN_TOKEN_AMOUNT;
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

        if (logs && logs.length) {
          for (const log of logs) {
            if (isValidTransfer(log)) {
              console.log(`✅ Valid transfer to ${log.targetAddress} found.`);
              console.log(`   Token: ${log.address}`);
              console.log(`   Amount: ${log.args.value.toString()}`);
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
