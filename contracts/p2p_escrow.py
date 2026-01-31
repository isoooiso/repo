# { "Depends": "py-genlayer:test" }

from genlayer import *
import json
import typing

class P2PEscrow(gl.Contract):
    offers: TreeMap[u256, str]     # offerId -> JSON
    deals: TreeMap[u256, str]      # offerId -> JSON (escrow/deal)
    next_offer_id: u256

    def __init__(self):
        self.next_offer_id = u256(1)

    # ---------- helpers ----------
    def _require(self, cond: bool, msg: str):
        if not cond:
            gl.advanced.user_error_immediate(msg)

    def _get_offer(self, offer_id: u256) -> dict:
        raw = self.offers.get(offer_id)
        self._require(raw is not None, "offer_not_found")
        return json.loads(raw)

    def _set_offer(self, offer_id: u256, offer: dict):
        self.offers[offer_id] = json.dumps(offer)

    def _get_deal(self, offer_id: u256) -> dict:
        raw = self.deals.get(offer_id)
        self._require(raw is not None, "deal_not_found")
        return json.loads(raw)

    def _set_deal(self, offer_id: u256, deal: dict):
        self.deals[offer_id] = json.dumps(deal)

    # ---------- views ----------
    @gl.public.view
    def get_offer(self, offer_id: u256) -> str:
        # returns JSON string
        return self.offers.get(offer_id) or ""

    @gl.public.view
    def get_deal(self, offer_id: u256) -> str:
        # returns JSON string
        return self.deals.get(offer_id) or ""

    @gl.public.view
    def get_next_offer_id(self) -> u256:
        return self.next_offer_id

    # ---------- core: offers ----------
    @gl.public.write
    def create_offer(self, title: str, description: str, price: u256) -> u256:
        sender = gl.message.sender
        offer_id = self.next_offer_id
        self.next_offer_id = u256(int(self.next_offer_id) + 1)

        offer = {
            "id": int(offer_id),
            "seller": str(sender),
            "title": title,
            "description": description,
            "price": int(price),
            "status": "OPEN"  # OPEN | TAKEN | CANCELLED | COMPLETED | DISPUTED
        }
        self._set_offer(offer_id, offer)
        return offer_id

    @gl.public.write
    def cancel_offer(self, offer_id: u256) -> None:
        sender = gl.message.sender
        offer = self._get_offer(offer_id)
        self._require(offer["seller"] == str(sender), "only_seller")
        self._require(offer["status"] == "OPEN", "not_open")
        offer["status"] = "CANCELLED"
        self._set_offer(offer_id, offer)

    # ---------- core: escrow/deal ----------
    @gl.public.write.payable
    def accept_offer(self, offer_id: u256) -> None:
        buyer = gl.message.sender
        value = gl.message.value

        offer = self._get_offer(offer_id)
        self._require(offer["status"] == "OPEN", "offer_not_open")
        self._require(int(value) == int(offer["price"]), "wrong_value")

        deal = {
            "offerId": int(offer_id),
            "buyer": str(buyer),
            "seller": offer["seller"],
            "price": int(offer["price"]),
            "state": "FUNDED",      # FUNDED | SHIPPED | COMPLETED | DISPUTED | RESOLVED
            "trackingUrl": "",
            "dispute": None,
        }
        self._set_deal(offer_id, deal)

        offer["status"] = "TAKEN"
        self._set_offer(offer_id, offer)

    @gl.public.write
    def mark_shipped(self, offer_id: u256, tracking_url: str) -> None:
        sender = gl.message.sender
        deal = self._get_deal(offer_id)
        self._require(deal["seller"] == str(sender), "only_seller")
        self._require(deal["state"] == "FUNDED", "bad_state")

        deal["state"] = "SHIPPED"
        deal["trackingUrl"] = tracking_url
        self._set_deal(offer_id, deal)

    @gl.public.write
    def confirm_received(self, offer_id: u256) -> None:
        sender = gl.message.sender
        deal = self._get_deal(offer_id)
        self._require(deal["buyer"] == str(sender), "only_buyer")
        self._require(deal["state"] == "SHIPPED", "bad_state")

        # pay seller
        seller_addr = Address(deal["seller"])
        amount = u256(deal["price"])
        gl.ContractAt(seller_addr).emit_transfer(value=amount)

        deal["state"] = "COMPLETED"
        self._set_deal(offer_id, deal)

        offer = self._get_offer(offer_id)
        offer["status"] = "COMPLETED"
        self._set_offer(offer_id, offer)

    # ---------- disputes ----------
    @gl.public.write
    def open_dispute(self, offer_id: u256, reason: str, evidence_urls_csv: str) -> None:
        # evidence_urls_csv: "https://... , https://..."
        sender = gl.message.sender
        deal = self._get_deal(offer_id)
        self._require(sender == Address(deal["buyer"]) or sender == Address(deal["seller"]), "only_party")
        self._require(deal["state"] in ["FUNDED", "SHIPPED"], "bad_state")

        deal["state"] = "DISPUTED"
        deal["dispute"] = {
            "openedBy": str(sender),
            "buyerReason": reason if str(sender) == deal["buyer"] else "",
            "sellerReason": reason if str(sender) == deal["seller"] else "",
            "buyerEvidence": evidence_urls_csv if str(sender) == deal["buyer"] else "",
            "sellerEvidence": evidence_urls_csv if str(sender) == deal["seller"] else "",
            "resolution": None
        }
        self._set_deal(offer_id, deal)

        offer = self._get_offer(offer_id)
        offer["status"] = "DISPUTED"
        self._set_offer(offer_id, offer)

    @gl.public.write
    def respond_dispute(self, offer_id: u256, response: str, evidence_urls_csv: str) -> None:
        sender = gl.message.sender
        deal = self._get_deal(offer_id)
        self._require(deal["state"] == "DISPUTED", "not_disputed")
        self._require(deal["dispute"] is not None, "no_dispute")

        if str(sender) == deal["buyer"]:
            deal["dispute"]["buyerReason"] = response
            deal["dispute"]["buyerEvidence"] = evidence_urls_csv
        elif str(sender) == deal["seller"]:
            deal["dispute"]["sellerReason"] = response
            deal["dispute"]["sellerEvidence"] = evidence_urls_csv
        else:
            self._require(False, "only_party")

        self._set_deal(offer_id, deal)

    @gl.public.write
    def resolve_dispute(self, offer_id: u256) -> str:
        deal_storage = self._get_deal(offer_id)
        self._require(deal_storage["state"] == "DISPUTED", "not_disputed")

        # Copy to memory to use inside nondet / equivalence principle blocks
        deal = gl.storage.copy_to_memory(deal_storage)

        def leader_llm_decision() -> str:
            # Optionally fetch readable text from URLs (best-effort)
            def render_urls(csv: str) -> str:
                csv = (csv or "").strip()
                if csv == "":
                    return ""
                urls = [u.strip() for u in csv.split(",") if u.strip() != ""]
                chunks = []
                # limit to avoid huge prompts
                for u in urls[:3]:
                    try:
                        # render() returns page text/html depending on mode
                        text = gl.nondet.web.render(u, mode="text")
                        # truncate
                        chunks.append(f"URL: {u}\nCONTENT:\n{text[:1200]}\n")
                    except:
                        chunks.append(f"URL: {u}\nCONTENT: (failed to fetch)\n")
                return "\n".join(chunks)

            dispute = deal["dispute"]
            buyer_ev = render_urls(dispute.get("buyerEvidence", ""))
            seller_ev = render_urls(dispute.get("sellerEvidence", ""))

            prompt = f"""
You are an escrow arbitrator. Decide a fair resolution for this P2P deal.

Return ONLY valid JSON (no markdown) with keys:
- "winner": "buyer" or "seller"
- "refund_pct": integer 0..100  (percent of escrow to refund to buyer)
- "rationale": short text (max 400 chars)

Case:
- price: {deal["price"]}
- state: {deal["state"]}
- trackingUrl: {deal.get("trackingUrl","")}

Buyer statement:
{dispute.get("buyerReason","")}

Seller statement:
{dispute.get("sellerReason","")}

Buyer evidence (rendered):
{buyer_ev}

Seller evidence (rendered):
{seller_ev}
"""
            # Let validators judge if output is acceptable (non-comparative)
            # We'll still ask for JSON-only output
            return gl.nondet.exec_prompt(prompt, response_format="json")

        criteria = """
Output must be valid JSON with keys winner, refund_pct, rationale.
winner must be exactly "buyer" or "seller".
refund_pct must be an integer between 0 and 100.
rationale must be <= 400 characters.
No extra keys.
"""

        result = gl.eq_principle.prompt_non_comparative(
            leader_llm_decision,
            task="Resolve an escrow dispute fairly based on statements and evidence",
            criteria=criteria
        )

        # result may already be dict if VM parses json, but to be safe:
        if isinstance(result, str):
            decision = json.loads(result)
        else:
            decision = result

        refund_pct = int(decision["refund_pct"])
        self._require(0 <= refund_pct <= 100, "bad_refund_pct")

        price = int(deal_storage["price"])
        refund_amount = (price * refund_pct) // 100
        seller_amount = price - refund_amount

        buyer_addr = Address(deal_storage["buyer"])
        seller_addr = Address(deal_storage["seller"])

        if refund_amount > 0:
            gl.ContractAt(buyer_addr).emit_transfer(value=u256(refund_amount))
        if seller_amount > 0:
            gl.ContractAt(seller_addr).emit_transfer(value=u256(seller_amount))

        deal_storage["state"] = "RESOLVED"
        deal_storage["dispute"]["resolution"] = decision
        self._set_deal(offer_id, deal_storage)

        offer = self._get_offer(offer_id)
        offer["status"] = "COMPLETED"
        self._set_offer(offer_id, offer)

        return json.dumps(decision)
