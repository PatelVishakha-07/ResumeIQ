from django.db import models

#User model 
class User(models.Model):
    role_choices = [
        ('user', 'User'),
        ('admin', 'Admin')
    ]

    user_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    email = models.EmailField( max_length=100, unique=True)
    password = models.CharField(max_length=255, null=True, blank=True)
    role = models.CharField(max_length=10, choices=role_choices, default='admin')
    status = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    #forces the table name to be user instead of accounts_user
    class Meta:
        db_table = 'user'

    def __Str__(self):
        return self.email

    