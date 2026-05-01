from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from evr_bot.models import User, SubscriptionStatus
from evr_bot.config import DATABASE_URL

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()

try:
    user = session.query(User).filter(User.email == "test_insert@gmail.com").first()
    if not user:
        user = User(email="test_insert@gmail.com", password_hash="hash")
        session.add(user)
        session.commit()
        print("Created user")
    
    user.subscription_status = SubscriptionStatus.ACTIVE
    session.commit()
    print("Updated user to ACTIVE successfully!")
except Exception as e:
    print(f"ERROR: {e}")
