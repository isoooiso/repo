import { createClient } from "genlayer-js";
import { createWalletClient, custom, parseUnits } from "viem";

// Minimal chain config (GenLayer testnet via Caldera)
const genlayerTestnet = {
  id: 4221,
  name: "GenLayer Testnet",
  nativeCurrency: { name: "GEN", symbol: "GEN", decimals: 18 },
  rpcUrls: {
    default: { http: ["https://genlayer-testnet.rpc.caldera.xyz/http"] }
  }
};

let account = null;
let walletClient = null;
let client = null;

const $ = (id) => document.getElementById(id);
const log = (msg) => ($("log").textContent = `${msg}\n` + $("log").textContent);

function getContract() {
  const address = $("contractAddress").value.trim();
  if (!address) throw new Error("Set contract address");
  return address;
}

async function ensureClient() {
  if (!account) throw new Error("Connect wallet first");
  if (!client) {
    client = createClient({
      chain: genlayerTestnet,
      // genlayer-js works over viem-like accounts; we can pass address only for reads,
      // but for writes we’ll rely on wallet signing
      account: { address: account }
    });
  }
  return client;
}

async function connect() {
  if (!window.ethereum) throw new Error("No injected wallet found");
  walletClient = createWalletClient({
    chain: genlayerTestnet,
    transport: custom(window.ethereum)
  });

  const [addr] = await walletClient.requestAddresses();
  account = addr;
  $("account").textContent = addr;
  log("Wallet connected: " + addr);
}

async function readOfferDeal(offerId) {
  const c = await ensureClient();
  const address = getContract();

  const offer = await c.readContract({
    address,
    functionName: "get_offer",
    args: [BigInt(offerId)]
  });

  const deal = await c.readContract({
    address,
    functionName: "get_deal",
    args: [BigInt(offerId)]
  });

  return { offer, deal };
}

// For writes we use genlayer-js writeContract (it creates tx for GenLayer nodes).
async function write(functionName, args = [], value = 0n) {
  const c = await ensureClient();
  const address = getContract();

  const tx = await c.writeContract({
    address,
    functionName,
    args,
    value
  });

  return tx;
}

$("btnConnect").onclick = async () => {
  try { await connect(); } catch (e) { log("ERR: " + e.message); }
};

$("btnCreate").onclick = async () => {
  try {
    const title = $("title").value;
    const desc = $("desc").value;
    const price = BigInt($("price").value);
    const tx = await write("create_offer", [title, desc, price]);
    log("create_offer tx: " + JSON.stringify(tx));
  } catch (e) { log("ERR: " + e.message); }
};

$("btnRead").onclick = async () => {
  try {
    const id = $("offerIdRead").value;
    const { offer, deal } = await readOfferDeal(id);
    $("readOut").textContent = "offer:\n" + offer + "\n\ndeal:\n" + deal;
  } catch (e) { log("ERR: " + e.message); }
};

$("btnAccept").onclick = async () => {
  try {
    const id = $("offerIdAccept").value;
    const { offer } = await readOfferDeal(id);
    if (!offer) throw new Error("Offer empty");
    const offerObj = JSON.parse(offer);
    const price = BigInt(offerObj.price);

    const tx = await write("accept_offer", [BigInt(id)], price);
    log("accept_offer tx: " + JSON.stringify(tx));
  } catch (e) { log("ERR: " + e.message); }
};

$("btnShip").onclick = async () => {
  try {
    const id = $("offerIdShip").value;
    const tracking = $("tracking").value;
    const tx = await write("mark_shipped", [BigInt(id), tracking]);
    log("mark_shipped tx: " + JSON.stringify(tx));
  } catch (e) { log("ERR: " + e.message); }
};

$("btnConfirm").onclick = async () => {
  try {
    const id = $("offerIdShip").value;
    const tx = await write("confirm_received", [BigInt(id)]);
    log("confirm_received tx: " + JSON.stringify(tx));
  } catch (e) { log("ERR: " + e.message); }
};

$("btnOpenDispute").onclick = async () => {
  try {
    const id = $("offerIdDispute").value;
    const reason = $("reason").value;
    const evidence = $("evidence").value;
    const tx = await write("open_dispute", [BigInt(id), reason, evidence]);
    log("open_dispute tx: " + JSON.stringify(tx));
  } catch (e) { log("ERR: " + e.message); }
};

$("btnRespondDispute").onclick = async () => {
  try {
    const id = $("offerIdDispute").value;
    const reason = $("reason").value;
    const evidence = $("evidence").value;
    const tx = await write("respond_dispute", [BigInt(id), reason, evidence]);
    log("respond_dispute tx: " + JSON.stringify(tx));
  } catch (e) { log("ERR: " + e.message); }
};

$("btnResolve").onclick = async () => {
  try {
    const id = $("offerIdDispute").value;
    const tx = await write("resolve_dispute", [BigInt(id)]);
    log("resolve_dispute tx: " + JSON.stringify(tx));
  } catch (e) { log("ERR: " + e.message); }
};
