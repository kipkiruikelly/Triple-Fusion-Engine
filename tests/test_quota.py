"""Free-tier quota: consumption, limit, and refund on failure."""

from models import FREE_DAILY_LIMIT


def test_quota_consume_limit_and_refund(app, db, make_user):
    from models import User
    from utils import consume_quota, refund_quota
    uid = make_user("quotauser")
    with app.app_context():
        u = db.session.get(User, uid)
        for _ in range(FREE_DAILY_LIMIT):
            assert consume_quota(u) is True
        assert consume_quota(u) is False          # limit reached
        refund_quota(u)                            # a failed prediction refunds
        assert u.predictions_today == FREE_DAILY_LIMIT - 1
        assert consume_quota(u) is True            # slot usable again


def test_pro_user_unlimited(app, db, make_user):
    from models import User
    from utils import consume_quota
    uid = make_user("prouser", plan="pro")
    with app.app_context():
        u = db.session.get(User, uid)
        for _ in range(FREE_DAILY_LIMIT + 5):
            assert consume_quota(u) is True
