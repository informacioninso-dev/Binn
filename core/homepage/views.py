from django.shortcuts import render, HttpResponse


# creamos la respuesta a la ruta homepage/1/
def homepage(request):
    return render(request,'homepage.html')

def login(request):
    return render(request,'login.html')