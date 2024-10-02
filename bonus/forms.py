from django import forms

from bonus.models import Order


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        user = cleaned_data.get('user')
        status = cleaned_data.get('status')

        if status == 'confirmed' and not user:
            raise forms.ValidationError("Confirmed orders must have an associated user.")

        return cleaned_data
