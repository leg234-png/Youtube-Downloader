# Importation des bibliothèques nécessaires
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from sklearn import datasets
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA


# Chargement du jeu de données Iris
iris = datasets.load_iris()
X = iris.data

df=pd.DataFrame(iris.data, columns=iris.feature_names)
df["species"]=iris.target_names[iris.target]
df.head()

##notre class ACP

class ACP:
    def __init__(self):
        return
    
    def fit(self, X:np.array, M=None, D=None, ):
        shape = X.shape 
        n= shape[0]
        p= shape[1]

        if D is None:
            D = np.diag(np.ones(n)/n)
       


        X_bar = X.T @ D @ np.ones(n)



        Y=X-np.ones(n).reshape(n,1) @ X_bar.reshape(1,p)

        if M is None :
           M= np.diag(np.ones(n)/n)


    ##Applying ACP with A sklearn Class

    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA


    #centrer et reduire 
    scaler = StandardScaler(with_mean=True, with_std=True)
    Z=scaler.fit_transform(X)

    pca=PCA()
    c=pca.fit_transform(Z)

    print(pca.explained_variance_ratio_)
    plt.figure()
    plt.scatter(c[0:50,0],c[0:50,1,], label=iris.target_names[0])
    plt.scatter(c[50:100,0],c[50:100,1,], label=iris.target_names[1])
    plt.scatter(c[100:150,0], c[100:150,1], label=iris.target_names[2])
    plt.legend()
    plt.show()



        
    
