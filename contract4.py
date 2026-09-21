# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
import genlayer.gl as gl
import json


class EvidenceConsensus(gl.Contract):
    """
    EvidenceConsensus

    Generic multi-source claim verification primitive.

    A user submits:
      - a claim
      - verification criteria
      - multiple evidence URLs

    During verification:
      1. The leader independently fetches all evidence.
      2. The leader evaluates the claim against the criteria.
      3. The leader returns a structured APPROVED/REJECTED verdict.
      4. The validator independently fetches the SAME evidence URLs.
      5. The validator independently evaluates the SAME claim and criteria.
      6. The validator's substantive verdict MUST exactly match the leader's
         substantive verdict.

    Importantly, the validator does NOT merely check that the leader's answer
    begins with APPROVED or REJECTED.

    Consensus rule:

        leader verdict == validator verdict

    Only after consensus is reached is the verified report stored on-chain.
    """

    def __init__(self):
        self.counter = 0

        # claim_id -> JSON string
        self.claims = TreeMap[str, str]()

    # ------------------------------------------------------------------
    # INTERNAL HELPERS
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_verdict(value):
        """
        Convert a model-produced verdict into one of the two allowed
        substantive decisions.
        """
        if not isinstance(value, str):
            return None

        verdict = value.strip().upper()

        if verdict == "APPROVED":
            return "APPROVED"

        if verdict == "REJECTED":
            return "REJECTED"

        return None

    @staticmethod
    def _build_evidence_block(evidence_items):
        """
        Convert fetched evidence into a compact, deterministic prompt block.
        """
        blocks = []

        for index, item in enumerate(evidence_items):
            url = item.get("url", "")
            content = item.get("content", "")

            blocks.append(
                "SOURCE {}\nURL: {}\nCONTENT:\n{}".format(
                    index + 1,
                    url,
                    content
                )
            )

        return "\n\n====================\n\n".join(blocks)

    @staticmethod
    def _fetch_evidence(urls):
        """
        Fetch every supplied source independently.

        This function is intended to run inside a nondeterministic execution
        block because it performs external web requests.
        """
        evidence = []

        for url in urls:
            response = gl.nondet.web.get(url)

            try:
                body = response.body.decode("utf-8")
            except Exception:
                body = str(response.body)

            evidence.append(
                {
                    "url": url,
                    "content": body
                }
            )

        return evidence

    @staticmethod
    def _evaluate_claim(claim, criteria, evidence):
        """
        Ask the LLM to independently evaluate the claim.

        The decision is deliberately separated from the explanation.

        The consensus mechanism compares ONLY `verdict`.
        Reasoning is stored for transparency but is not required to be
        textually identical between nodes.
        """

        evidence_block = EvidenceConsensus._build_evidence_block(evidence)

        prompt = f"""
You are an independent evidence verifier.

Your task is to determine whether a CLAIM is substantively supported
by the supplied EVIDENCE according to the supplied CRITERIA.

Do NOT trust any previous verifier decision.

You must perform the assessment yourself.

CLAIM:
{claim}

CRITERIA:
{criteria}

EVIDENCE:
{evidence_block}

DECISION RULES:

1. APPROVED means the evidence sufficiently satisfies the criteria
   and supports the claim.

2. REJECTED means the evidence does not sufficiently satisfy the criteria,
   contradicts the claim, is insufficient, or cannot establish the claim.

3. Do not approve merely because a source contains words similar to the claim.

4. Evaluate the actual meaning and substance of the evidence.

5. If important evidence is missing or ambiguous, use REJECTED.

6. Do not infer unsupported facts.

7. The verdict must be a substantive conclusion about the claim,
   not a statement about whether the response format is valid.

Return ONLY a JSON object with exactly these fields:

{{
    "verdict": "APPROVED" or "REJECTED",
    "reasoning": "brief explanation based on the evidence",
    "supporting_sources": ["source numbers that materially support the decision"]
}}
"""

        result = gl.nondet.exec_prompt(
            prompt,
            response_format="json"
        )

        if not isinstance(result, dict):
            raise gl.UserError("Verifier returned a non-object result")

        verdict = EvidenceConsensus._normalize_verdict(
            result.get("verdict")
        )

        if verdict is None:
            raise gl.UserError("Verifier returned an invalid verdict")

        reasoning = result.get("reasoning", "")

        if not isinstance(reasoning, str):
            reasoning = str(reasoning)

        supporting_sources = result.get("supporting_sources", [])

        if not isinstance(supporting_sources, list):
            supporting_sources = []

        return {
            "verdict": verdict,
            "reasoning": reasoning,
            "supporting_sources": supporting_sources
        }

    # ------------------------------------------------------------------
    # CREATE CLAIM
    # ------------------------------------------------------------------

    @gl.public.write
    def create_claim(
        self,
        claim: str,
        criteria: str,
        evidence_urls: list[str]
    ) -> str:
        """
        Create a claim awaiting verification.

        Example:

        claim:
            "The Eiffel Tower is located in Paris."

        criteria:
            "The evidence must explicitly establish the location
             of the Eiffel Tower."

        evidence_urls:
            [
                "https://example.com/source1",
                "https://example.com/source2"
            ]
        """

        if not isinstance(claim, str) or len(claim.strip()) == 0:
            raise gl.vm.UserError("Claim cannot be empty")

        if not isinstance(criteria, str) or len(criteria.strip()) == 0:
            raise gl.vm.UserError("Criteria cannot be empty")

        if not isinstance(evidence_urls, list):
            raise gl.vm.UserError("Evidence URLs must be a list")

        if len(evidence_urls) == 0:
            raise gl.vm.UserError("At least one evidence URL is required")

        if len(evidence_urls) > 10:
            raise gl.vm.UserError(
                "A maximum of 10 evidence sources is allowed"
            )

        normalized_urls = []

        for url in evidence_urls:
            if not isinstance(url, str):
                raise gl.vm.UserError(
                    "Every evidence URL must be a string"
                )

            clean_url = url.strip()

            if len(clean_url) == 0:
                raise gl.vm.UserError(
                    "Evidence URL cannot be empty"
                )

            normalized_urls.append(clean_url)

        self.counter += 1

        claim_id = str(self.counter)

        record = {
            "id": claim_id,
            "claim": claim.strip(),
            "criteria": criteria.strip(),
            "evidence_urls": normalized_urls,
            "status": "PENDING",
            "verdict": "",
            "reasoning": "",
            "supporting_sources": [],
            "created_at": gl.block.timestamp
        }

        self.claims[claim_id] = json.dumps(record)

        return claim_id

    # ------------------------------------------------------------------
    # VERIFY CLAIM
    # ------------------------------------------------------------------

    @gl.public.write
    def verify_claim(self, claim_id: str):
        """
        Independently verify a claim through GenLayer consensus.

        The critical security property is:

            leader.verdict == validator.verdict

        The validator does NOT simply validate the leader's label.

        It independently:
          - fetches the evidence
          - reads the claim
          - reads the criteria
          - evaluates the evidence
          - derives its own verdict
        """

        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")

        stored = json.loads(self.claims[claim_id])

        if stored.get("status") == "APPROVED":
            raise gl.vm.UserError("Claim already approved")

        if stored.get("status") == "REJECTED":
            raise gl.vm.UserError("Claim already rejected")

        claim = stored["claim"]
        criteria = stored["criteria"]
        evidence_urls = stored["evidence_urls"]

        # --------------------------------------------------------------
        # IMPORTANT:
        #
        # Copy all required values into local memory before entering
        # nondeterministic consensus logic.
        #
        # The nested leader/validator functions do NOT read self.
        # --------------------------------------------------------------

        local_claim = claim
        local_criteria = criteria
        local_urls = list(evidence_urls)

        def leader_fn():
            """
            Leader performs the complete verification independently.
            """

            evidence = EvidenceConsensus._fetch_evidence(
                local_urls
            )

            result = EvidenceConsensus._evaluate_claim(
                local_claim,
                local_criteria,
                evidence
            )

            return {
                "verdict": result["verdict"],
                "reasoning": result["reasoning"],
                "supporting_sources": result["supporting_sources"],
                "evidence": evidence
            }

        def validator_fn(leader_result):
            """
            Validator independently repeats the COMPLETE substantive task.

            This is the key difference from a label-only validator.

            It does not ask:
                "Did leader say APPROVED?"

            It asks:
                "Given the same claim, criteria and independently fetched
                 evidence, do I independently reach the SAME substantive
                 decision?"
            """

            if not isinstance(leader_result, gl.vm.Return):
                return False

            leader_data = leader_result.calldata

            if not isinstance(leader_data, dict):
                return False

            leader_verdict = EvidenceConsensus._normalize_verdict(
                leader_data.get("verdict")
            )

            if leader_verdict is None:
                return False

            # Independently fetch the same URLs.
            validator_evidence = EvidenceConsensus._fetch_evidence(
                local_urls
            )

            # Independently evaluate the claim.
            validator_result = EvidenceConsensus._evaluate_claim(
                local_claim,
                local_criteria,
                validator_evidence
            )

            validator_verdict = EvidenceConsensus._normalize_verdict(
                validator_result.get("verdict")
            )

            if validator_verdict is None:
                return False

            # ----------------------------------------------------------
            # CRITICAL CONSENSUS CHECK
            #
            # The validator must independently reach the same substantive
            # APPROVED / REJECTED decision.
            #
            # Reasoning does NOT need to match word-for-word.
            # Evidence order does not need to match.
            # Only the substantive decision must match.
            # ----------------------------------------------------------

            return leader_verdict == validator_verdict

        # --------------------------------------------------------------
        # Execute consensus.
        #
        # No storage mutation occurs inside the nondeterministic blocks.
        # --------------------------------------------------------------

        consensus_result = gl.vm.run_nondet_unsafe(
            leader_fn,
            validator_fn
        )

        if not isinstance(consensus_result, dict):
            raise gl.vm.UserError(
                "Consensus returned an invalid result"
            )

        final_verdict = EvidenceConsensus._normalize_verdict(
            consensus_result.get("verdict")
        )

        if final_verdict is None:
            raise gl.vm.UserError(
                "Consensus returned an invalid verdict"
            )

        # --------------------------------------------------------------
        # ONLY NOW modify deterministic contract storage.
        # --------------------------------------------------------------

        stored["status"] = final_verdict
        stored["verdict"] = final_verdict
        stored["reasoning"] = consensus_result.get(
            "reasoning",
            ""
        )
        stored["supporting_sources"] = consensus_result.get(
            "supporting_sources",
            []
        )

        # Store the evidence actually returned by the consensus result.
        stored["verified_evidence"] = consensus_result.get(
            "evidence",
            []
        )

        stored["verified_at"] = gl.block.timestamp

        self.claims[claim_id] = json.dumps(stored)

        return stored

    # ------------------------------------------------------------------
    # READ CLAIM
    # ------------------------------------------------------------------

    @gl.public.view
    def get_claim(self, claim_id: str):
        """
        Return a complete claim record.
        """

        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")

        return json.loads(self.claims[claim_id])

    # ------------------------------------------------------------------
    # READ VERDICT
    # ------------------------------------------------------------------

    @gl.public.view
    def get_verdict(self, claim_id: str) -> str:
        """
        Return only the final consensus verdict.
        """

        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")

        stored = json.loads(self.claims[claim_id])

        return stored.get("verdict", "")

    # ------------------------------------------------------------------
    # READ STATUS
    # ------------------------------------------------------------------

    @gl.public.view
    def get_status(self, claim_id: str) -> str:
        """
        Return PENDING / APPROVED / REJECTED.
        """

        if claim_id not in self.claims:
            raise gl.vm.UserError("Claim not found")

        stored = json.loads(self.claims[claim_id])

        return stored.get("status", "PENDING")

    # ------------------------------------------------------------------
    # READ COUNTER
    # ------------------------------------------------------------------

    @gl.public.view
    def get_counter(self) -> int:
        """
        Return number of submitted claims.
        """

        return self.counter

    # ------------------------------------------------------------------
    # READ LATEST ID
    # ------------------------------------------------------------------

    @gl.public.view
    def get_latest_id(self) -> str:
        """
        Return the most recently created claim ID.
        """

        if self.counter == 0:
            return ""

        return str(self.counter)
