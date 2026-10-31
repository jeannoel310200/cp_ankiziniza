from faker import Faker
from random import randint,choice
from locust import HttpUser,task, between

fake = Faker()

class RegisterUser(HttpUser):
    wait_time = between(1,2)

    @task
    def register(self):
        first_name = fake.first_name().capitalize()
        last_name = fake.last_name().capitalize()

        GENDERS = ["male","female"]

        password = "password"

        name_for_email = first_name.lower()

        nombre = randint(1000,9999)

        payload = {
            "first_name":first_name,
            "last_name":last_name,
            "email":f"{name_for_email}{nombre}@gmail.com",
            "password": password,
            "phone":None,
            "gender": choice(GENDERS)
        }

        with self.client.post(
            "/api/v1/users/register",
            json=payload,
            name="POST /api/v1/users/register",
            catch_response=True
        ) as response:
            if response.status_code==201:
                response.success()
            else:
                response.failure(f"{response.status_code} - {response.text}")



