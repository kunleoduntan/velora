"""Workflow approvals: every transition names who may act, each round of approvals starts clean, maker-checker is available, parallel branches need different people, and starting needs write access."""
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select

from velora import db, new_doc
from velora.controlplane.role_admin import RoleAdministration
from velora.exceptions import PermissionDenied, ValidationError
from velora.permissions import Session, session_as
from velora.workflow_automation import votes
from velora.workflows import act, get_instance, save_definition, start

ADMIN = SimpleNamespace(is_company_admin=True, email="admin@company.test", roles={"System Manager"})
S = lambda user, *roles: Session(user, frozenset({*roles, "Sales User"}))  # noqa: E731


def customer(owner="Administrator"):
    if owner == "Administrator":
        return new_doc("Customer", customer_name="WF Customer").insert()
    with session_as(Session(owner, frozenset({"System Manager"}))):
        return new_doc("Customer", customer_name="WF Customer").insert()


def define(transitions, states=("Pending", "Draft", "Approved"), name="WF"):
    return save_definition({"name": name, "doctype": "Customer", "initial_state": "Pending", "states": [{"name": n, **({"is_final": True} if n == "Approved" else {})} for n in states],
                            "transitions": transitions})


QUORUM = {"action": "Approve", "from_state": "Pending", "to_state": "Approved", "roles": ["Approver"], "approval_mode": "quorum", "required_approvals": 2, "final": True}
REJECT = {"action": "Reject", "from_state": "Pending", "to_state": "Draft", "roles": ["Approver"]}
RESUBMIT = {"action": "Resubmit", "from_state": "Draft", "to_state": "Pending", "roles": ["Sales User"]}


# ============================== a transition must say who may act ==============================
def test_a_transition_without_roles_or_users_is_refused_unless_anyone_is_explicit(site):
    with pytest.raises(ValidationError, match="must say who may perform it"):
        define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved"}])
    with pytest.raises(ValidationError, match="must be true or false"):
        define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "anyone": "yes"}])
    define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "anyone": True}])                  # a deliberate, visible choice
    define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "users": ["boss@acme.ng"]}])
    define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "roles": ["Approver"]}])


def test_every_parallel_branch_must_say_who_approves_it(site):
    branch = {"key": "finance", "label": "Finance"}
    tr = {"action": "Approve", "from_state": "Pending", "to_state": "Approved", "parallel_steps": [branch]}
    with pytest.raises(ValidationError, match="Parallel branch 'finance' must say who may approve it"):
        define([tr])
    define([{**tr, "parallel_steps": [{**branch, "roles": ["Finance Manager"]}]}])
    define([{**tr, "parallel_steps": [{**branch, "anyone": True}]}], name="WF2")


# ============================== each round of approvals starts clean ==============================
def test_approvals_from_an_earlier_round_do_not_count_toward_the_next_and_people_can_vote_again(site):
    define([QUORUM, REJECT, RESUBMIT])
    inst = start("WF", "Customer", customer().name)["id"]
    with session_as(S("approver.one", "Approver")):
        act(inst, "Approve", "round 1")                                                                              # 1 of 2
    with session_as(S("approver.two", "Approver")):
        assert act(inst, "Reject", "needs changes")["state"] == "Draft"
    with session_as(S("maker", "Sales User")):
        assert act(inst, "Resubmit", "fixed")["state"] == "Pending"
    with session_as(S("approver.one", "Approver")):
        again = act(inst, "Approve", "round 2")                                                                      # used to fail: "You have already voted"
        assert again["state"] == "Pending"                                                                           # and round 1's vote does NOT make this the second approval
    with session_as(S("approver.two", "Approver")):
        done = act(inst, "Approve", "round 2")
        assert done["state"] == "Approved" and done["status"] == "Completed"
    rounds = sorted((v["actor"], v["round"]) for v in get_instance(inst)["approval_votes"])
    assert len(rounds) == 3 and len({r for _, r in rounds}) == 2                                                     # all three votes are kept as evidence, in two rounds


def test_approvals_cast_before_rounds_existed_still_count(site):
    """Votes from an older version have no round; an upgrade must not lose approvals that are in flight."""
    define([QUORUM])
    inst = start("WF", "Customer", customer().name)["id"]
    with db.transaction() as c:
        c.execute(insert(votes).values(id="legacy1", instance_id=inst, action="Approve", actor="old.approver", decision="Approve", comment="", created_on=__import__("datetime").datetime.utcnow()))
    with session_as(S("approver.new", "Approver")):
        assert act(inst, "Approve")["state"] == "Approved"                                                           # 1 legacy + 1 new = the quorum of 2


def test_a_person_cannot_vote_twice_in_the_same_round(site):
    define([QUORUM])
    inst = start("WF", "Customer", customer().name)["id"]
    with session_as(S("approver.one", "Approver")):
        act(inst, "Approve")
        with pytest.raises(ValidationError, match="already voted"):
            act(inst, "Approve")


# ============================== maker-checker ==============================
def test_the_person_who_started_the_request_cannot_approve_it_when_the_step_says_so(site):
    define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "roles": ["Approver"], "prevent_self_approval": True, "final": True}])
    with session_as(Session("maker", frozenset({"Approver", "Sales User", "System Manager"}))):
        inst = start("WF", "Customer", customer().name)["id"]
        with pytest.raises(PermissionDenied, match="cannot approve it \\(separation of duties\\)"):
            act(inst, "Approve")                                                                                    # holds the role, but started it
    with session_as(S("checker", "Approver")):
        assert act(inst, "Approve")["status"] == "Completed"


def test_the_owner_of_the_document_cannot_approve_it_either(site):
    define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "roles": ["Approver"], "prevent_self_approval": True, "final": True}])
    doc = customer(owner="clerk@acme.ng")
    inst = start("WF", "Customer", doc.name)["id"]                                                                   # started by someone else (Administrator)
    with session_as(S("clerk@acme.ng", "Approver")):
        with pytest.raises(PermissionDenied, match="separation of duties"):
            act(inst, "Approve")


def test_without_the_flag_nothing_changes_and_the_administrator_is_exempt(site):
    define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "roles": ["Approver"], "final": True}], name="Plain")
    with session_as(Session("maker", frozenset({"Approver", "Sales User", "System Manager"}))):
        inst = start("Plain", "Customer", customer().name)["id"]
        assert act(inst, "Approve")["status"] == "Completed"                                                        # no flag: the maker may approve (as before)
    define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "roles": ["Approver"], "prevent_self_approval": True, "final": True}], name="Strict")
    inst = start("Strict", "Customer", customer().name)["id"]                                                       # started by Administrator
    assert act(inst, "Approve")["status"] == "Completed"                                                            # Administrator is never locked out


# ============================== parallel branches need different people ==============================
PARALLEL = {"action": "Approve", "from_state": "Pending", "to_state": "Approved", "final": True,
            "parallel_steps": [{"key": "finance", "label": "Finance", "roles": ["Finance Manager"]}, {"key": "risk", "label": "Risk", "roles": ["Risk Manager"]}]}


def test_one_person_cannot_satisfy_every_parallel_branch_alone(site):
    define([PARALLEL])
    inst = start("WF", "Customer", customer().name)["id"]
    both = S("both@acme.ng", "Finance Manager", "Risk Manager")
    with session_as(both):
        assert act(inst, "Approve", "finance ok", "finance")["state"] == "Pending"
        with pytest.raises(ValidationError, match="each branch needs a different approver"):
            act(inst, "Approve", "risk ok", "risk")                                                                  # one person holding both roles
    with session_as(S("risk@acme.ng", "Risk Manager")):
        assert act(inst, "Approve", "risk ok", "risk")["status"] == "Completed"                                     # a second person completes it


def test_the_administrator_may_still_approve_every_branch(site):
    define([PARALLEL])
    inst = start("WF", "Customer", customer().name)["id"]
    act(inst, "Approve", "", "finance")
    assert act(inst, "Approve", "", "risk")["status"] == "Completed"


# ============================== starting needs write access ==============================
def test_a_record_you_may_read_but_not_write_cannot_have_a_workflow_started_on_it(site):
    define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "roles": ["Approver"], "final": True}])
    svc = RoleAdministration(db.get_engine())
    svc.create_role(ADMIN, "Branch Clerk")
    for op in ("create", "read", "write"):
        svc.set_permission(ADMIN, "Branch Clerk", "Customer", op, True)
    svc.set_row_policy(ADMIN, "Branch Clerk", "Customer", "write", [{"field": "owner", "operator": "equals_user"}])      # may READ anything, may WRITE only their own
    with session_as(Session("bob@acme.ng", frozenset({"Branch Clerk"}))):
        theirs = new_doc("Customer", customer_name="Bob's customer").insert()
    with session_as(Session("alice@acme.ng", frozenset({"Branch Clerk"}))):
        with pytest.raises(PermissionDenied, match="outside the permitted Customer record scope"):
            start("WF", "Customer", theirs.name)
    with session_as(Session("bob@acme.ng", frozenset({"Branch Clerk"}))):
        assert start("WF", "Customer", theirs.name)["state"] == "Pending"


# ============================== child workflows and SLAs ==============================
def test_an_ordinary_user_cannot_launch_a_child_workflow_to_push_someone_elses_approval_through(site):
    from velora.workflow_orchestration import start_child
    save_definition({"name": "Parent", "doctype": "Customer", "initial_state": "Pending", "states": [{"name": "Pending"}, {"name": "Approved", "is_final": True}],
                     "transitions": [{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "roles": ["Approver"], "final": True}]})
    save_definition({"name": "Trivial child", "doctype": "Customer", "initial_state": "Open", "states": [{"name": "Open"}, {"name": "Done", "is_final": True}],
                     "transitions": [{"action": "Finish", "from_state": "Open", "to_state": "Done", "anyone": True, "final": True}]})
    doc = customer()
    parent = start("Parent", "Customer", doc.name)["id"]
    with session_as(S("clerk@acme.ng")):
        with pytest.raises(PermissionDenied, match="System Manager"):
            start_child(parent, "Trivial child", "Approved")                                                         # the attack: resume_state = Approved
    assert get_instance(parent)["state"] == "Pending" and get_instance(parent)["status"] == "Active"                 # nothing moved
    assert start_child(parent, "Trivial child", "Approved")["parent_status"] == "Waiting"                            # an administrator still can


def test_the_sla_of_a_workflow_is_visible_only_to_people_who_can_read_its_document(site):
    from velora.workflow_automation import get_sla
    define([{"action": "Approve", "from_state": "Pending", "to_state": "Approved", "roles": ["Approver"], "final": True}])
    inst = start("WF", "Customer", customer().name)["id"]
    get_sla(inst)                                                                                                    # the Administrator may
    with session_as(S("reader@acme.ng")):
        get_sla(inst)                                                                                                # so may someone who can read Customers
    with session_as(Session("stranger@acme.ng", frozenset({"Stranger"}))):
        with pytest.raises(PermissionDenied):
            get_sla(inst)
